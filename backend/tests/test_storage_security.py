import fcntl
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from boxen.media.infrastructure.storage import file_hash
from boxen.operations.infrastructure.backup import Backups
from boxen.operations.infrastructure.database import initialize
from boxen.platform.application import Application
from boxen.shared.errors import DomainError


@pytest.fixture
def backup(settings):
    initialize(settings)
    app = Application(settings)
    root = settings.data_dir / "backups/backup-security-test"
    app.backups.create({"relative_path": root.name})
    with app.database.transaction() as repo:
        installation = repo.setting("installation_id")
    yield app, root, installation
    app.database.close()


def write_manifest(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest))


def refresh_manifest(root, manifest):
    for key in manifest["files"]:
        manifest["files"][key] = {"sha256": file_hash(root / key), "bytes": (root / key).stat().st_size}
    checksums = "".join(f"{entry['sha256']}  {key}\n" for key, entry in manifest["files"].items())
    (root / "checksums.sha256").write_text(checksums)
    manifest.update(
        checksums_sha256=hashlib.sha256(checksums.encode()).hexdigest(),
        file_count=len(manifest["files"]),
        total_bytes=sum(entry["bytes"] for entry in manifest["files"].values()),
    )
    write_manifest(root, manifest)


@pytest.mark.parametrize("field", ["file_count", "total_bytes"])
def test_verify_rejects_inconsistent_manifest_totals(backup, field):
    _, root, _ = backup
    manifest = Backups.verify(root)
    manifest[field] += 1
    write_manifest(root, manifest)
    with pytest.raises(DomainError):
        Backups.verify(root)


@pytest.mark.parametrize("change", ["missing", "duplicate", "digest", "extra"])
def test_verify_cross_checks_checksum_entries_even_with_correct_list_hash(backup, change):
    _, root, _ = backup
    manifest = Backups.verify(root)
    lines = (root / "checksums.sha256").read_text().splitlines(keepends=True)
    if change == "missing":
        lines.pop()
    elif change == "duplicate":
        lines.append(lines[0])
    elif change == "digest":
        lines[0] = "0" * 64 + lines[0][64:]
    else:
        lines.append("0" * 64 + "  unlisted-file\n")
    checksums = "".join(lines)
    (root / "checksums.sha256").write_text(checksums)
    manifest["checksums_sha256"] = hashlib.sha256(checksums.encode()).hexdigest()
    write_manifest(root, manifest)
    with pytest.raises(DomainError, match="does not match"):
        Backups.verify(root)


@pytest.mark.parametrize("key", ["manifest.json", "checksums.sha256", "configuration"])
def test_verify_rejects_symlinked_metadata_and_parent_directories(backup, key):
    _, root, _ = backup
    original = root / key
    moved = root / (key + ".saved")
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(DomainError, match="unsafe path"):
        Backups.verify(root)


def test_verify_rejects_duplicate_json_keys(backup):
    _, root, _ = backup
    content = (root / "manifest.json").read_text()
    (root / "manifest.json").write_text('{"format_version": 9,' + content[1:])
    with pytest.raises(DomainError):
        Backups.verify(root)


@pytest.mark.parametrize("mutation", ["installation", "schema"])
def test_verify_checks_snapshot_identity_and_migration_history(backup, mutation):
    _, root, _ = backup
    manifest = Backups.verify(root)
    db = sqlite3.connect(root / "boxen.sqlite3")
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        if mutation == "installation":
            db.execute(
                "UPDATE app_settings SET value_json='\"other-installation\"' WHERE key='installation_id'"
            )
        else:
            db.execute("UPDATE schema_migrations SET checksum_sha256=?", ("0" * 64,))
        db.commit()
    finally:
        db.close()
    refresh_manifest(root, manifest)
    with pytest.raises(DomainError, match="identity or migration"):
        Backups.verify(root)


def test_verify_database_uri_escapes_special_characters(backup):
    _, root, _ = backup
    renamed = root.with_name("backup # question?")
    root.rename(renamed)
    assert Backups.verify(renamed)["database_integrity"] == "ok"


def test_restore_ignores_unlisted_media_and_preserves_runtime_lock(backup):
    app, root, installation = backup
    manifest = Backups.verify(root)
    listed_key = "media/originals/fixture.png"
    listed = root / listed_key
    listed.parent.mkdir(parents=True)
    listed.write_bytes(b"verified original bytes")
    manifest["files"][listed_key] = {}
    refresh_manifest(root, manifest)
    (root / "media/unlisted.txt").write_text("unchecked bytes")
    (root / "media/unlisted-link").symlink_to(app.settings.data_dir / "secrets/session.key")
    lock_path = app.settings.data_dir / "db/runtime.lock"
    inode = lock_path.stat().st_ino

    result = app.backups.restore(root, installation, apply=True)

    assert (app.settings.data_dir / listed_key).read_bytes() == b"verified original bytes"
    assert not (app.settings.data_dir / "media/unlisted.txt").exists()
    assert not (app.settings.data_dir / "media/unlisted-link").exists()
    assert lock_path.stat().st_ino == inode
    assert (Path(result["quarantine"]) / "db/boxen.sqlite3").is_file()
    assert app.settings.database_path.stat().st_mode & 0o077 == 0


def test_restore_rechecks_copied_bytes_before_quarantining_live_data(backup, monkeypatch):
    app, root, installation = backup
    original_copy = shutil.copyfile
    live_inode = app.settings.data_dir.stat().st_ino

    def changed_copy(source, destination, **kwargs):
        result = original_copy(source, destination, **kwargs)
        if Path(source) == root / "boxen.sqlite3":
            with Path(destination).open("ab") as target:
                target.write(b"changed after verification")
        return result

    monkeypatch.setattr(shutil, "copyfile", changed_copy)
    with pytest.raises(DomainError, match="changed during restore"):
        app.backups.restore(root, installation, apply=True)
    assert app.settings.data_dir.stat().st_ino == live_inode
    assert not list(app.settings.data_dir.parent.glob("data.quarantine-*"))
    with app.database.transaction() as repo:
        assert repo.execute("PRAGMA integrity_check").scalar() == "ok"


def test_operations_runner_defers_without_changing_inflight_backup(client, monkeypatch):
    app = client.app.state.services
    response = client.post("/api/v1/backups")
    assert response.status_code == 202
    backup_id = response.json()["id"]
    original_create = app.backups.create

    def concurrent_create(row):
        assert app.operations.run_once() is False
        with app.database.transaction() as repo:
            assert repo.one("backups", id=backup_id)["status"] == "creating"
        return original_create(row)

    monkeypatch.setattr(app.backups, "create", concurrent_create)
    assert app.operations.run_once() is True
    with app.database.transaction() as repo:
        assert repo.one("backups", id=backup_id)["status"] == "verified"


def test_backup_lock_contention_does_not_mark_pending_backup_failed(client):
    app = client.app.state.services
    response = client.post("/api/v1/backups")
    assert response.status_code == 202
    with (app.settings.data_dir / "db/backup.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert app.operations.run_once() is False
    with app.database.transaction() as repo:
        assert repo.one("backups", id=response.json()["id"])["status"] == "creating"
    assert app.operations.run_once() is True
