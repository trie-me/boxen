import hashlib
from pathlib import Path

from alembic import command
from alembic.config import Config

ASSETS = Path(__file__).resolve().parents[2] / "assets"
MIGRATION_SOURCES = {
    "0001": "schema.sql",
    "0002": "migrations/0002_organization.sql",
    "0003": "migrations/0003_authentication.sql",
}
CURRENT_SCHEMA_VERSION = "0003"


def migration_history(assets: Path = ASSETS) -> list[tuple[str, str]]:
    """Historical checksums cover the immutable SQL payload for each revision."""
    return [
        (version, hashlib.sha256((assets / source).read_bytes()).hexdigest())
        for version, source in MIGRATION_SOURCES.items()
    ]


def validate_history(
    execute,
    *,
    assets: Path = ASSETS,
    allow_empty: bool = False,
    allow_legacy: bool = False,
    required_version: str | None = None,
) -> str | None:
    """Validate both ledgers before any DDL or stamping, including known old snapshots."""
    tables = {
        row[0]
        for row in execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    if not tables and allow_empty:
        return None
    message = "Database migration history is incompatible with this release."
    if "schema_migrations" not in tables:
        raise RuntimeError(message)
    rows = [
        tuple(row)
        for row in execute("SELECT version,checksum_sha256 FROM schema_migrations ORDER BY version")
    ]
    expected = migration_history(assets)
    if not rows or rows != expected[: len(rows)]:
        raise RuntimeError(message)
    version = rows[-1][0]
    if required_version is not None and version != required_version:
        raise RuntimeError(message)
    if "alembic_version" not in tables:
        if not allow_legacy or version != "0001":
            raise RuntimeError(message)
    elif [tuple(row) for row in execute("SELECT version_num FROM alembic_version")] != [(version,)]:
        raise RuntimeError(message)
    return version


def upgrade_database(database):
    """Caller owns the offline migration lock. Every DDL change is transactional."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    with database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            version = validate_history(
                connection.exec_driver_sql,
                assets=database.settings.assets,
                allow_empty=True,
                allow_legacy=True,
            )
            config.attributes["connection"] = connection
            tables = {
                r[0] for r in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if version is not None and "alembic_version" not in tables:
                command.stamp(config, version)
            command.upgrade(config, "head")
            validate_history(
                connection.exec_driver_sql,
                assets=database.settings.assets,
                required_version=CURRENT_SCHEMA_VERSION,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
