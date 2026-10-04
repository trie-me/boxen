import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from boxen import __version__
from boxen.media.infrastructure.storage import ObjectStore, check_space, file_hash
from boxen.operations.infrastructure.database import Database
from boxen.operations.infrastructure.migrate import MIGRATION_SOURCES, upgrade_database, validate_history
from boxen.shared.errors import DomainError, require
from boxen.shared.values import new_id, now


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_file(root: Path, key: str) -> Path:
    """Reject aliases and symlinks in every component of a backup file path."""
    path = root / key
    require(
        bool(key)
        and not Path(key).is_absolute()
        and all(part not in {"", ".", ".."} for part in key.split("/"))
        and not any(ord(char) < 32 or char == "\\" for char in key)
        and not any(part.is_symlink() for part in (path, *path.parents) if part != root.parent)
        and path.is_file(),
        "backup.invalid_path",
        "A backup file is missing or has an unsafe path.",
    )
    return path


def unique_object(pairs):
    value = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError("Duplicate backup metadata key")
        value[key] = entry
    return value


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        os.fchmod(file.fileno(), 0o600)
        json.dump(value, file, sort_keys=True, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    sync_directory(path.parent)


class Backups:
    def __init__(self, settings, database):
        self.settings, self.database = settings, database

    def path(self, row: dict) -> Path:
        root = (self.settings.data_dir / "backups").resolve()
        path = (root / row["relative_path"]).resolve()
        require(
            path.is_relative_to(root) and path != root, "backup.invalid_path", "Invalid backup location.", 500
        )
        return path

    def create(self, row: dict) -> dict:
        check_space(self.settings)
        root = self.path(row)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.settings.data_dir / "db/backup.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            snapshot_path = root / "boxen.sqlite3"
            source = sqlite3.connect(str(self.settings.database_path))
            snapshot = sqlite3.connect(str(snapshot_path))
            try:
                source.backup(snapshot, pages=128)
                require(
                    snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    "backup.database_invalid",
                    "The database snapshot failed its integrity check.",
                )
                require(
                    not snapshot.execute("PRAGMA foreign_key_check").fetchall(),
                    "backup.database_invalid",
                    "The database snapshot has broken references.",
                )
                schema_version = validate_history(snapshot.execute, allow_legacy=True)
                keys = snapshot.execute(
                    "SELECT DISTINCT original_storage_key FROM box_images WHERE lifecycle='ready'"
                ).fetchall()
                installation = json.loads(
                    snapshot.execute(
                        "SELECT value_json FROM app_settings WHERE key='installation_id'"
                    ).fetchone()[0]
                )
            finally:
                source.close()
                snapshot.close()
            store = ObjectStore(self.settings.data_dir / "media")
            for (key,) in keys:
                destination = root / "media" / key
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(store.path(key), destination)
                destination.chmod(0o600)
            (root / "configuration").mkdir(exist_ok=True, mode=0o700)
            atomic_json(
                root / "configuration/public-settings.json",
                {
                    "origin": self.settings.origin,
                    "model_profile": self.settings.ai_profile,
                    "backup_retention": self.settings.backup_retention,
                },
            )
            files: dict[str, dict[str, Any]] = {
                str(path.relative_to(root)): {"sha256": file_hash(path), "bytes": path.stat().st_size}
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.name not in {"manifest.json", "checksums.sha256"}
            }
            checksums = "".join(f"{entry['sha256']}  {key}\n" for key, entry in files.items())
            with (root / "checksums.sha256").open("w") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(checksums)
                file.flush()
                os.fsync(file.fileno())
            # A verified manifest must not precede durable payload bytes/directory entries.
            for key in files:
                path = root / key
                path.chmod(0o600)
                with path.open("rb") as file:
                    os.fsync(file.fileno())
            for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
                sync_directory(directory)
            manifest = {
                "format_version": 1,
                "application_version": __version__,
                "schema_version": schema_version,
                "created_at": now(),
                "installation_id": installation,
                "database_integrity": "ok",
                "file_count": len(files),
                "total_bytes": sum(f["bytes"] for f in files.values()),
                "files": files,
                "checksums_sha256": hashlib.sha256(checksums.encode()).hexdigest(),
                "model_profile": self.settings.ai_profile,
            }
            atomic_json(root / "manifest.json", manifest)
            sync_directory(root.parent)
            self.verify(root)
            return {
                "manifest_sha256": file_hash(root / "manifest.json"),
                "database_sha256": file_hash(snapshot_path),
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
            }

    @staticmethod
    def verify(root: Path) -> dict:
        root = root.resolve()
        try:
            manifest = json.loads(
                backup_file(root, "manifest.json").read_text(), object_pairs_hook=unique_object
            )
            require(
                manifest["format_version"] == 1 and manifest["schema_version"] in MIGRATION_SOURCES,
                "backup.incompatible",
                "This backup format or schema is unsupported.",
            )
            require(
                file_hash(backup_file(root, "checksums.sha256")) == manifest["checksums_sha256"],
                "backup.checksum_invalid",
                "The backup checksum list was modified.",
            )
            require(
                isinstance(manifest["files"], dict) and "boxen.sqlite3" in manifest["files"],
                "backup.incomplete",
                "The backup has no database snapshot.",
            )
            files = manifest["files"]
            require(
                type(manifest["file_count"]) is int and manifest["file_count"] == len(files),
                "backup.incomplete",
                "The backup file count does not match its manifest.",
            )
            for key, entry in manifest["files"].items():
                path = backup_file(root, key)
                require(
                    key not in {"manifest.json", "checksums.sha256"}
                    and type(entry["bytes"]) is int
                    and entry["bytes"] >= 0
                    and isinstance(entry["sha256"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                    "backup.invalid",
                    "The backup contains invalid file metadata.",
                )
                require(
                    path.stat().st_size == entry["bytes"] and file_hash(path) == entry["sha256"],
                    "backup.checksum_invalid",
                    "A backup file failed its checksum check.",
                )
            require(
                type(manifest["total_bytes"]) is int
                and manifest["total_bytes"] == sum(entry["bytes"] for entry in files.values())
                and sorted((root / "checksums.sha256").read_text().splitlines())
                == sorted(f"{entry['sha256']}  {key}" for key, entry in files.items()),
                "backup.checksum_invalid",
                "The checksum list or byte total does not match the manifest.",
            )
            # Snapshots are standalone files; never consume an unverified WAL sidecar.
            db = sqlite3.connect((root / "boxen.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                require(
                    db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    and not db.execute("PRAGMA foreign_key_check").fetchall(),
                    "backup.database_invalid",
                    "The backup database failed validation.",
                )
                require(
                    json.loads(
                        db.execute(
                            "SELECT value_json FROM app_settings WHERE key='installation_id'"
                        ).fetchone()[0]
                    )
                    == manifest["installation_id"],
                    "backup.database_invalid",
                    "The snapshot identity or migration history does not match this backup and release.",
                )
                try:
                    validate_history(
                        db.execute, allow_legacy=True, required_version=manifest["schema_version"]
                    )
                except RuntimeError:
                    raise DomainError(
                        "backup.database_invalid",
                        "The snapshot identity or migration history does not match this backup and release.",
                    ) from None
                for key, digest, size in db.execute(
                    "SELECT original_storage_key,sha256,byte_size FROM box_images WHERE lifecycle='ready'"
                ):
                    require(
                        "media/" + key in manifest["files"]
                        and key.startswith("originals/")
                        and manifest["files"]["media/" + key]["sha256"] == digest
                        and manifest["files"]["media/" + key]["bytes"] == size,
                        "backup.media_missing",
                        "The backup is missing a referenced original photo.",
                    )
            finally:
                db.close()
            return manifest
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, sqlite3.DatabaseError):
            raise DomainError("backup.invalid", "The backup is incomplete or invalid.") from None

    def restore(self, backup_path: Path, confirmation: str, apply: bool = False) -> dict:
        backup_path = backup_path.resolve()
        manifest = self.verify(backup_path)
        with self.database.transaction() as repo:
            installation_id = repo.setting("installation_id")
        require(
            confirmation == installation_id == manifest["installation_id"],
            "restore.wrong_installation",
            "The installation confirmation does not match this host and backup.",
        )
        fingerprint = hashlib.sha256(self.settings.password_pepper()).hexdigest()
        with sqlite3.connect(
            (backup_path / "boxen.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True
        ) as snapshot:
            row = snapshot.execute(
                "SELECT value_json FROM app_settings WHERE key='password_pepper_fingerprint'"
            ).fetchone()
            require(
                row is None or json.loads(row[0]) == fingerprint,
                "restore.pepper_mismatch",
                "Restore the password pepper belonging to this backup before restoring its database.",
            )
        if not apply:
            return {
                "status": "ready",
                "file_count": manifest["file_count"],
                "schema_version": manifest["schema_version"],
            }
        # The service holds shared runtime locks; restore requires the exclusive lock.
        lock_path = self.settings.data_dir / "db/runtime.lock"
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DomainError(
                    "restore.services_running", "Stop the web and worker services before restoring."
                ) from None
            check_space(self.settings)
            source_root = self.settings.data_dir
            require(
                source_root.name not in {"", ".", ".."} and source_root.parent != source_root,
                "restore.invalid_target",
                "Invalid restore data directory.",
            )
            restored = source_root.with_name(source_root.name + ".restore-" + new_id())
            quarantine = source_root.with_name(source_root.name + ".quarantine-" + new_id())
            restored.mkdir(mode=0o700)
            for directory in ("db", "media", "secrets", "tmp", "backups", "models"):
                (restored / directory).mkdir(mode=0o700)
            for directory in ("staging", "originals", "display", "thumbnails"):
                (restored / "media" / directory).mkdir(mode=0o700)
            # Preserve the lock inode across activation so new openers cannot bypass it.
            os.link(lock_path, restored / "db/runtime.lock")
            restored_database = restored / self.settings.database_path.relative_to(source_root)
            for key, entry in manifest["files"].items():
                if key != "boxen.sqlite3" and not key.startswith("media/"):
                    continue
                destination = restored_database if key == "boxen.sqlite3" else restored / key
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(backup_file(backup_path, key), destination)
                destination.chmod(0o600)
                require(
                    destination.stat().st_size == entry["bytes"]
                    and file_hash(destination) == entry["sha256"],
                    "backup.checksum_invalid",
                    "A backup file changed during restore. The current data was preserved.",
                )
                with destination.open("rb") as file:
                    os.fsync(file.fileno())
            shutil.copytree(source_root / "secrets", restored / "secrets", dirs_exist_ok=True)
            # A configured pepper can reside elsewhere under data_dir; preserve it across the directory swap.
            pepper_path = self.settings.password_pepper_file
            if pepper_path.is_relative_to(source_root):
                restored_pepper = restored / pepper_path.relative_to(source_root)
                restored_pepper.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(pepper_path, restored_pepper)
                restored_pepper.chmod(0o600)
                require(
                    file_hash(restored_pepper) == fingerprint,
                    "restore.pepper_mismatch",
                    "The password pepper changed during restore. The current data was preserved.",
                )
                with restored_pepper.open("rb") as file:
                    os.fsync(file.fileno())
            # Models and backup history remain reachable after restore; no destructive removal.
            for directory in ("models", "backups"):
                shutil.copytree(
                    source_root / directory, restored / directory, dirs_exist_ok=True, copy_function=os.link
                )
            # Upgrade only the verified staging copy; original backup bytes and manifest stay immutable.
            staged = Database(
                self.settings.model_copy(update={"data_dir": restored, "database_path": restored_database})
            )
            try:
                upgrade_database(staged)
                staged.check_schema()
            finally:
                staged.close()
            db = sqlite3.connect(str(restored_database))
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("UPDATE sessions SET revoked_at=?", (now(),))
            db.execute("DELETE FROM oidc_transactions")
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated_at) VALUES('password_pepper_fingerprint',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (json.dumps(fingerprint), now()),
            )
            db.execute("DELETE FROM idempotency_records")
            db.execute(
                "DELETE FROM app_settings WHERE key IN ('worker_heartbeat', 'ai_readiness', 'last_media_sweep')"
            )
            db.execute(
                "UPDATE analysis_jobs SET state='cancelled',lease_token=NULL,lease_owner=NULL,lease_expires_at=NULL,completed_at=?,updated_at=? WHERE state IN ('queued','running')",
                (now(), now()),
            )
            db.execute(
                "UPDATE maintenance_jobs SET state='cancelled',lease_token=NULL,lease_owner=NULL,lease_expires_at=NULL,completed_at=?,updated_at=? WHERE state IN ('queued','running')",
                (now(), now()),
            )
            db.execute(
                "UPDATE backups SET status='failed',completed_at=?,error_code='backup.interrupted_by_restore',error_summary='This operation was interrupted by an offline restore.' WHERE status IN ('creating','verifying')",
                (now(),),
            )
            db.commit()
            require(
                db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                and not db.execute("PRAGMA foreign_key_check").fetchall(),
                "backup.database_invalid",
                "The upgraded restore database failed validation. The current data was preserved.",
            )
            db.close()
            with restored_database.open("rb") as file:
                os.fsync(file.fileno())
            for directory in sorted((p for p in restored.rglob("*") if p.is_dir()), reverse=True):
                sync_directory(directory)
            sync_directory(restored)
            self.database.close()
            source_root.rename(quarantine)
            try:
                restored.rename(source_root)
            except BaseException:
                quarantine.rename(source_root)
                raise
            sync_directory(source_root.parent)
            return {
                "status": "restored",
                "quarantine": str(quarantine),
                "next": "Run boxen repair-derivatives and boxen verify before starting services.",
            }
