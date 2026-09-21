import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from typing import Any

from boxen.operations.infrastructure.migrate import CURRENT_SCHEMA_VERSION, validate_history
from boxen.platform.config import Settings
from boxen.shared.values import now
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection

TABLES = {
    "users",
    "sessions",
    "app_settings",
    "idempotency_records",
    "boxes",
    "box_code_tombstones",
    "box_images",
    "inventory_items",
    "analysis_jobs",
    "ai_runs",
    "item_observations",
    "audit_log",
    "maintenance_jobs",
    "backups",
    "label_profiles",
    "search_projection_state",
    "tags",
    "box_tags",
    "collections",
    "collection_boxes",
}


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z_0-9]*", value):
        raise ValueError("Invalid SQL identifier")
    return value


class Repository:
    """Transaction-scoped persistence adapter. Callers never commit independently."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def execute(self, sql: str, values: dict | None = None):
        return self.connection.execute(text(sql), values or {})

    def rows(self, sql: str, values: dict | None = None) -> list[dict]:
        return [dict(row) for row in self.execute(sql, values).mappings()]

    def one(self, table: str, **where) -> dict | None:
        rows = self.find(table, **where)
        return rows[0] if rows else None

    def find(self, table: str, **where) -> list[dict]:
        self._table(table)
        clause = " AND ".join(f"{identifier(key)} IS :{key}" for key in where) or "1=1"
        return self.rows(f"SELECT * FROM {table} WHERE {clause}", where)

    def insert(self, table: str, data: dict) -> None:
        self._table(table)
        columns = ",".join(identifier(key) for key in data)
        params = ",".join(":" + key for key in data)
        self.execute(f"INSERT INTO {table} ({columns}) VALUES ({params})", data)

    def update(self, table: str, data: dict, **where) -> None:
        self._table(table)
        if not where:
            raise ValueError("An update requires an exact predicate")
        columns = ",".join(f"{identifier(key)} = :set_{key}" for key in data)
        clause = " AND ".join(f"{identifier(key)} IS :where_{key}" for key in where)
        self.execute(
            f"UPDATE {table} SET {columns} WHERE {clause}",
            {**{f"set_{k}": v for k, v in data.items()}, **{f"where_{k}": v for k, v in where.items()}},
        )

    def delete(self, table: str, **where) -> None:
        self._table(table)
        if not where:
            raise ValueError("A delete requires an exact predicate")
        clause = " AND ".join(f"{identifier(key)} IS :{key}" for key in where)
        self.execute(f"DELETE FROM {table} WHERE {clause}", where)

    def setting(self, key: str, default: Any = None) -> Any:
        row = self.one("app_settings", key=key)
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO app_settings(key,value_json,updated_at) VALUES(:k,:v,:t) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
            {"k": key, "v": json.dumps(value, sort_keys=True), "t": now()},
        )

    def audit(
        self,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        metadata: dict | None = None,
    ) -> None:
        self.insert(
            "audit_log",
            {
                "occurred_at": now(),
                "actor_user_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_public_id": target_id,
                "request_id": request_id,
                "metadata_json": json.dumps(metadata or {}, sort_keys=True),
            },
        )

    @staticmethod
    def _table(table: str) -> None:
        if table not in TABLES:
            raise ValueError("Unknown repository table")


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(
            f"sqlite:///{settings.database_path}",
            pool_size=4,
            max_overflow=0,
            connect_args={"check_same_thread": False, "timeout": 5},
        )

        @event.listens_for(self.engine, "connect")
        def configure(connection, _record):
            connection.enable_load_extension(False)
            for pragma in (
                "foreign_keys=ON",
                "journal_mode=WAL",
                "synchronous=FULL",
                "busy_timeout=5000",
                "temp_store=MEMORY",
            ):
                connection.execute(f"PRAGMA {pragma}")

    @contextmanager
    def transaction(self, write: bool = False):
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield Repository(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def check_schema(self) -> None:
        with self.transaction() as repo:
            validate_history(
                repo.connection.exec_driver_sql,
                assets=self.settings.assets,
                required_version=CURRENT_SCHEMA_VERSION,
            )
            repo.execute("SELECT box_id,tag_names,collection_names FROM box_search LIMIT 0")

    def close(self) -> None:
        self.engine.dispose()


def initialize(settings: Settings) -> str | None:
    """Explicit, locked initial migration; never invoked by HTTP startup."""
    os.umask(0o077)
    for name in (
        "db",
        "secrets",
        "media/staging",
        "media/originals",
        "media/display",
        "media/thumbnails",
        "models",
        "backups",
        "tmp",
    ):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    with (settings.data_dir / "db/migration.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        database = Database(settings)
        from boxen.operations.infrastructure.migrate import upgrade_database

        try:
            with (settings.data_dir / "db/runtime.lock").open("a+") as runtime_lock:
                fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                upgrade_database(database)
                database.check_schema()
                assert settings.session_key_file is not None
                if not settings.session_key_file.exists():
                    settings.session_key_file.write_bytes(secrets.token_bytes(32))
                    settings.session_key_file.chmod(0o600)
                setup_path = settings.data_dir / "secrets/setup-token"
                token = None
                with database.transaction(write=True) as repo:
                    if not repo.find("users") and not repo.setting("setup_token_hash"):
                        token = secrets.token_urlsafe(32)
                        setup_path.write_text(token)
                        setup_path.chmod(0o600)
                        repo.set_setting("setup_token_hash", hashlib.sha256(token.encode()).hexdigest())
                return token
        finally:
            database.close()
