"""Only disposable databases: preserve the deployed v1 schema and backup bytes."""

import fcntl
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from boxen.discovery.infrastructure.search import verify_search
from boxen.operations.infrastructure.backup import Backups
from boxen.operations.infrastructure.database import Database, initialize
from boxen.operations.infrastructure.migrate import (
    ASSETS,
    CURRENT_SCHEMA_VERSION,
    migration_history,
    upgrade_database,
    validate_history,
)
from boxen.shared.errors import DomainError
from sqlalchemy import event

AT = "2026-09-20T00:00:00Z"
V1_CHECKSUM = "1effd3c03ed9efa59da79100a36fe90f6c9a69b4261f9f42f296f21a84b0ec95"
V1_MIGRATION_CHECKSUM = "6836cad9056153cf1b93f171083360726cb78b59922fc1ce6ce244e0d9bd0457"


def v1_database(settings, *, legacy=False):
    for directory in (
        "db",
        "secrets",
        "backups",
        "models",
        "tmp",
        "media/originals",
        "media/staging",
        "media/display",
        "media/thumbnails",
    ):
        (settings.data_dir / directory).mkdir(parents=True, exist_ok=True)
    settings.session_key_file.write_bytes(b"test-only-session-identity-000001")
    settings.session_key_file.chmod(0o600)
    original = settings.data_dir / "media/originals/fixture.png"
    original.write_bytes(b"test-only-original-photo-bytes")
    with sqlite3.connect(settings.database_path) as db:
        db.executescript((ASSETS / "schema.sql").read_text())
        db.execute("INSERT INTO schema_migrations VALUES (?,?,?)", ("0001", V1_CHECKSUM, AT))
        if not legacy:
            db.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            db.execute("INSERT INTO alembic_version VALUES ('0001')")
        db.execute("INSERT INTO app_settings VALUES ('installation_id', ?, ?)", ('"fixture-install"', AT))
        db.execute(
            "INSERT INTO users (id,username,username_key,display_name,role,password_hash,created_at,updated_at) "
            "VALUES ('user','owner','owner','Owner','owner','test-only-hash',?,?)",
            (AT, AT),
        )
        db.execute(
            "INSERT INTO sessions (token_hash,user_id,credential_version,csrf_secret_hash,created_at,last_seen_at,expires_at) "
            "VALUES (?,'user',1,?,?,?,?)",
            ("1" * 64, "2" * 64, AT, AT, "2099-01-01T00:00:00Z"),
        )
        for box_id, name, lifecycle in (
            ("box", "Café repair kit", "active"),
            ("archived", "Archived telescope", "archived"),
        ):
            db.execute(
                "INSERT INTO boxes (id,public_code,name,description_text,markdown_renderer_version,lifecycle,created_by,updated_by,created_at,updated_at,archived_at) "
                "VALUES (?,?,?,'Full original description','test',?,'user','user',?,?,?)",
                (box_id, box_id + "code", name, lifecycle, AT, AT, AT if lifecycle == "archived" else None),
            )
        for item_id, name, notes, lifecycle in (
            ("a", "Adjustable wrench", "First complete item note", "active"),
            ("b", "Spare washers", "Second complete item note", "active"),
            ("c", "Discarded fixture", "Do not index removed inventory", "removed"),
        ):
            db.execute(
                "INSERT INTO inventory_items (id,box_id,name,normalized_name,notes_text,markdown_renderer_version,provenance,lifecycle,created_by,updated_by,created_at,updated_at,removed_at) "
                "VALUES (?,'box',?,?,?,'test','manual',?,'user','user',?,?,?)",
                (
                    item_id,
                    name,
                    name.casefold(),
                    notes,
                    lifecycle,
                    AT,
                    AT,
                    AT if lifecycle == "removed" else None,
                ),
            )
        db.execute(
            "INSERT INTO box_images (id,box_id,lifecycle,original_storage_key,display_storage_key,thumbnail_storage_key,original_filename,sha256,media_type,byte_size,width,height,created_by,created_at,updated_at) "
            "VALUES ('image','box','ready','originals/fixture.png','display/fixture.webp','thumbnails/fixture.webp','fixture.png',?,'image/png',?,1,1,'user',?,?)",
            (hashlib.sha256(original.read_bytes()).hexdigest(), original.stat().st_size, AT, AT),
        )
        # Deliberately stale derived data must be rebuilt from authoritative rows.
        db.execute("INSERT INTO box_search (box_id,name) VALUES ('box','stale title')")


def snapshot(settings):
    with sqlite3.connect(settings.database_path) as db:
        return list(db.iterdump())


def add_organization(database):
    with database.transaction(write=True) as repo:
        repo.insert("tags", {"id": "tag", "name": "Tools", "normalized_name": "tools", "created_at": AT})
        repo.insert(
            "collections",
            {
                "id": "collection",
                "name": "Workshop",
                "normalized_name": "workshop",
                "created_at": AT,
                "updated_at": AT,
            },
        )
        repo.insert("box_tags", {"box_id": "box", "tag_id": "tag"})
        repo.insert("collection_boxes", {"collection_id": "collection", "box_id": "box"})
        repo.execute("UPDATE box_search SET tag_names='Tools',collection_names='Workshop' WHERE box_id='box'")


def test_historical_schema_and_migration_bytes_are_immutable():
    root = ASSETS.parents[2]
    assert hashlib.sha256((ASSETS / "schema.sql").read_bytes()).hexdigest() == V1_CHECKSUM
    assert (
        hashlib.sha256((root / "docs/system-design/contracts/schema.sql").read_bytes()).hexdigest()
        == V1_CHECKSUM
    )
    assert (
        hashlib.sha256(
            (ASSETS.parent / "operations/infrastructure/migrations/versions/0001_initial.py").read_bytes()
        ).hexdigest()
        == V1_MIGRATION_CHECKSUM
    )
    assert (ASSETS / "migrations/0002_organization.sql").read_bytes() == (
        root / "docs/system-design/contracts/migrations/0002_organization.sql"
    ).read_bytes()


def test_fresh_initialization_uses_exact_two_revision_history(settings):
    assert initialize(settings)
    database = Database(settings)
    try:
        database.check_schema()
        with database.transaction() as repo:
            assert [
                tuple(row)
                for row in repo.execute(
                    "SELECT version,checksum_sha256 FROM schema_migrations ORDER BY version"
                )
            ] == migration_history()
            assert repo.execute("SELECT version_num FROM alembic_version").scalar() == CURRENT_SCHEMA_VERSION
            assert {row["name"] for row in repo.rows("PRAGMA table_list") if row["strict"]} >= {
                "tags",
                "box_tags",
                "collections",
                "collection_boxes",
            }
            assert [row["name"] for row in repo.rows("PRAGMA table_info(box_search)")] == [
                "box_id",
                "code",
                "name",
                "description",
                "item_names",
                "item_notes",
                "tag_names",
                "collection_names",
            ]
    finally:
        database.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_upgrade_rebuilds_complete_search_preserving_identity_and_inventory(settings, legacy):
    v1_database(settings, legacy=legacy)
    secret = settings.session_key_file.read_bytes()
    with sqlite3.connect(settings.database_path) as db:
        before = {
            table: db.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "users",
                "sessions",
                "boxes",
                "inventory_items",
                "box_images",
                "app_settings",
            )
        }
    assert initialize(settings) is None
    assert initialize(settings) is None
    assert settings.session_key_file.read_bytes() == secret
    with sqlite3.connect(settings.database_path) as db:
        for table, rows in before.items():
            assert db.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert db.execute("SELECT applied_at FROM schema_migrations WHERE version='0001'").fetchone() == (AT,)
        assert db.execute("SELECT * FROM box_search WHERE box_id='box'").fetchone() == (
            "box",
            "boxcode",
            "Café repair kit",
            "Full original description",
            "Adjustable wrench\nSpare washers",
            "First complete item note\nSecond complete item note",
            "",
            "",
        )
        assert db.execute("SELECT box_id FROM box_search WHERE box_search MATCH 'telescope'").fetchall() == [
            ("archived",)
        ]
        assert db.execute("SELECT box_id FROM box_search WHERE box_search MATCH 'washers'").fetchall() == [
            ("box",)
        ]
        assert not db.execute("SELECT box_id FROM box_search WHERE box_search MATCH 'discarded'").fetchall()
        for table in ("tags", "box_tags", "collections", "collection_boxes"):
            assert not db.execute(f"SELECT * FROM {table}").fetchall()
        assert db.execute(
            "SELECT projection_version,source_row_count,projection_row_count,state FROM search_projection_state"
        ).fetchone() == ("box-search-v2", 2, 2, "ready")
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    database = Database(settings)
    try:
        with database.transaction() as repo:
            assert verify_search(repo)["mismatches"] == 0
    finally:
        database.close()


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("failure", ["CREATE TABLE collections", "INSERT INTO schema_migrations"])
def test_failed_upgrade_rolls_back_ddl_fts_ledger_and_legacy_stamp(settings, legacy, failure):
    v1_database(settings, legacy=legacy)
    before = snapshot(settings)
    database = Database(settings)

    def fail(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith(failure):
            raise RuntimeError("injected migration failure")

    event.listen(database.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            upgrade_database(database)
    finally:
        database.close()
    assert snapshot(settings) == before
    assert initialize(settings) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "checksum",
        "future",
        "gap",
        "alembic_future",
        "alembic_ahead",
        "alembic_empty",
        "missing_ledger",
        "empty_ledger",
    ],
)
def test_invalid_history_is_rejected_before_migration_or_stamp(settings, monkeypatch, mutation):
    v1_database(settings)
    with sqlite3.connect(settings.database_path) as db:
        if mutation == "checksum":
            db.execute("UPDATE schema_migrations SET checksum_sha256=?", ("0" * 64,))
        elif mutation in {"future", "gap"}:
            revision, checksum = migration_history()[1]
            db.execute(
                "INSERT INTO schema_migrations VALUES (?,?,?)",
                (
                    "9999" if mutation == "future" else revision,
                    checksum,
                    AT,
                ),
            )
            if mutation == "gap":
                db.execute("DELETE FROM schema_migrations WHERE version='0001'")
        elif mutation in {"alembic_future", "alembic_ahead"}:
            db.execute(
                "UPDATE alembic_version SET version_num=?",
                ("9999" if mutation == "alembic_future" else "0002",),
            )
        elif mutation == "alembic_empty":
            db.execute("DELETE FROM alembic_version")
        elif mutation == "missing_ledger":
            db.execute("DROP TABLE schema_migrations")
        else:
            db.execute("DELETE FROM schema_migrations")
    before = snapshot(settings)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid history reached Alembic mutation")

    monkeypatch.setattr("boxen.operations.infrastructure.migrate.command.stamp", forbidden)
    monkeypatch.setattr("boxen.operations.infrastructure.migrate.command.upgrade", forbidden)
    with pytest.raises(RuntimeError, match="migration history"):
        initialize(settings)
    assert snapshot(settings) == before


def test_corrupt_legacy_history_is_never_stamped(settings, monkeypatch):
    v1_database(settings, legacy=True)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE schema_migrations SET checksum_sha256=?", ("0" * 64,))
    before = snapshot(settings)
    with pytest.raises(RuntimeError, match="migration history"):
        initialize(settings)
    assert snapshot(settings) == before


def test_runtime_lock_prevents_upgrade(settings):
    v1_database(settings)
    before = snapshot(settings)
    with (settings.data_dir / "db/runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            initialize(settings)
    assert snapshot(settings) == before


def test_schema_check_rejects_old_revision(settings):
    v1_database(settings)
    database = Database(settings)
    try:
        with pytest.raises(RuntimeError, match="migration history"):
            database.check_schema()
    finally:
        database.close()


@pytest.mark.parametrize(
    "invalid",
    [
        "INSERT INTO tags VALUES ('other','TOOLS','tools','now')",
        "INSERT INTO collections VALUES ('other','Workshop','workshop','',1,'now','now')",
        "UPDATE collections SET version=0",
        "UPDATE collections SET version=1.5",
        "INSERT INTO box_tags VALUES ('missing','tag')",
        "INSERT INTO collection_boxes VALUES ('collection','missing')",
        "INSERT INTO box_tags VALUES ('box','tag')",
        "INSERT INTO collection_boxes VALUES ('collection','box')",
    ],
)
def test_organization_constraints(settings, invalid):
    v1_database(settings)
    initialize(settings)
    database = Database(settings)
    add_organization(database)
    database.close()
    with sqlite3.connect(settings.database_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(invalid)


@pytest.mark.parametrize("deleted", ["boxes", "tags", "collections"])
def test_relationship_cascades_and_reverse_indexes(settings, deleted):
    v1_database(settings)
    initialize(settings)
    database = Database(settings)
    add_organization(database)
    database.close()
    with sqlite3.connect(settings.database_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        assert [row[2] for row in db.execute("PRAGMA index_info(ix_box_tags_tag_box)")] == [
            "tag_id",
            "box_id",
        ]
        assert [row[2] for row in db.execute("PRAGMA index_info(ix_collection_boxes_box_collection)")] == [
            "box_id",
            "collection_id",
        ]
        db.execute(f"DELETE FROM {deleted}")
        assert db.execute("SELECT count(*) FROM box_tags").fetchone()[0] == (
            1 if deleted == "collections" else 0
        )
        assert db.execute("SELECT count(*) FROM collection_boxes").fetchone()[0] == (
            1 if deleted == "tags" else 0
        )


@pytest.mark.parametrize("version,legacy", [("0001", False), ("0001", True), ("0002", False)])
def test_backup_versions_restore_offline_without_rewriting_old_artifacts(settings, version, legacy):
    v1_database(settings, legacy=legacy)
    if version == "0002":
        initialize(settings)
    database = Database(settings)
    if version == "0002":
        add_organization(database)
    backups = Backups(settings, database)
    row = {"relative_path": "version-fixture"}
    backups.create(row)
    root = backups.path(row)
    manifest_bytes = (root / "manifest.json").read_bytes()
    snapshot_bytes = (root / "boxen.sqlite3").read_bytes()
    manifest = backups.verify(root)
    assert manifest["schema_version"] == version
    if version == "0001":
        # Exercise rollback from a current host to its historical snapshot.
        database.close()
        initialize(settings)
        database = Database(settings)
        add_organization(database)
        backups = Backups(settings, database)
    secret = settings.session_key_file.read_bytes()
    lock_path = settings.data_dir / "db/runtime.lock"
    lock_path.touch()
    lock_inode = lock_path.stat().st_ino
    assert backups.restore(root, "fixture-install")["schema_version"] == version
    with database.transaction(write=True) as repo:
        repo.execute("UPDATE boxes SET name='Changed after backup' WHERE id='box'")
    result = backups.restore(root, "fixture-install", apply=True)
    assert Path(result["quarantine"]).is_dir()
    assert lock_path.stat().st_ino == lock_inode
    assert (root / "manifest.json").read_bytes() == manifest_bytes
    assert (root / "boxen.sqlite3").read_bytes() == snapshot_bytes
    assert backups.verify(root) == manifest
    assert settings.session_key_file.read_bytes() == secret
    assert (
        settings.data_dir / "media/originals/fixture.png"
    ).read_bytes() == b"test-only-original-photo-bytes"
    restored = Database(settings)
    try:
        restored.check_schema()
        with restored.transaction() as repo:
            assert repo.setting("installation_id") == "fixture-install"
            assert repo.one("boxes", id="box")["name"] == "Café repair kit"
            session = repo.find("sessions")[0]
            assert session["user_id"] == "user" and session["token_hash"] == "1" * 64
            assert session["revoked_at"] is not None
            assert len(repo.find("tags")) == (1 if version == "0002" else 0)
            assert len(repo.find("collection_boxes")) == (1 if version == "0002" else 0)
            assert (
                repo.execute("SELECT item_names FROM box_search WHERE box_id='box'").scalar()
                == "Adjustable wrench\nSpare washers"
            )
            assert verify_search(repo)["mismatches"] == 0
    finally:
        restored.close()


def test_restore_upgrade_failure_preserves_current_directory_and_backup(settings, monkeypatch):
    v1_database(settings)
    database = Database(settings)
    backups = Backups(settings, database)
    backups.create({"relative_path": "old-backup"})
    root = settings.data_dir / "backups/old-backup"
    before = snapshot(settings)
    manifest_bytes = (root / "manifest.json").read_bytes()

    def fail(_database):
        raise RuntimeError("injected staging upgrade failure")

    monkeypatch.setattr("boxen.operations.infrastructure.backup.upgrade_database", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            backups.restore(root, "fixture-install", apply=True)
        assert not list(settings.data_dir.parent.glob("data.quarantine-*"))
        assert snapshot(settings) == before
        assert (root / "manifest.json").read_bytes() == manifest_bytes
    finally:
        database.close()


def test_old_backup_restore_respects_runtime_lock(settings):
    v1_database(settings)
    database = Database(settings)
    backups = Backups(settings, database)
    backups.create({"relative_path": "old-backup"})
    try:
        with (settings.data_dir / "db/runtime.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with pytest.raises(DomainError, match="Stop the web"):
                backups.restore(settings.data_dir / "backups/old-backup", "fixture-install", apply=True)
        assert not list(settings.data_dir.parent.glob("data.restore-*"))
    finally:
        database.close()


@pytest.mark.parametrize("version", ["0001", "0002"])
def test_backup_manifest_version_must_match_snapshot(settings, version):
    v1_database(settings)
    if version == "0002":
        initialize(settings)
    database = Database(settings)
    backups = Backups(settings, database)
    try:
        backups.create({"relative_path": "mismatch"})
        root = settings.data_dir / "backups/mismatch"
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["schema_version"] = "0002" if version == "0001" else "0001"
        (root / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(DomainError, match="identity or migration"):
            backups.verify(root)
    finally:
        database.close()


def test_unknown_database_is_not_adopted_as_fresh(settings):
    settings.database_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
        with pytest.raises(RuntimeError, match="migration history"):
            validate_history(db.execute, allow_empty=True, allow_legacy=True)


@pytest.mark.parametrize("version", ["0001", "0002"])
def test_backup_creation_rejects_corrupt_history(settings, version):
    v1_database(settings)
    if version == "0002":
        initialize(settings)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE schema_migrations SET checksum_sha256=? WHERE version=?", ("0" * 64, version))
    database = Database(settings)
    try:
        with pytest.raises(RuntimeError, match="migration history"):
            Backups(settings, database).create({"relative_path": "corrupt-history"})
        assert not (settings.data_dir / "backups/corrupt-history/manifest.json").exists()
    finally:
        database.close()


@pytest.mark.parametrize("mutation", ["checksum", "missing_alembic", "behind_alembic", "future"])
def test_current_history_cannot_be_repaired_by_reinitializing(settings, mutation):
    initialize(settings)
    with sqlite3.connect(settings.database_path) as db:
        if mutation == "checksum":
            db.execute("UPDATE schema_migrations SET checksum_sha256=? WHERE version='0002'", ("0" * 64,))
        elif mutation == "missing_alembic":
            db.execute("DROP TABLE alembic_version")
        elif mutation == "behind_alembic":
            db.execute("UPDATE alembic_version SET version_num='0001'")
        else:
            db.execute("INSERT INTO schema_migrations VALUES ('9999',?,?)", ("0" * 64, AT))
    before = snapshot(settings)
    database = Database(settings)
    try:
        with pytest.raises(RuntimeError, match="migration history"):
            database.check_schema()
    finally:
        database.close()
    with pytest.raises(RuntimeError, match="migration history"):
        initialize(settings)
    assert snapshot(settings) == before
