"""Initial STRICT SQLite schema, FTS5 projection and checksum ledger."""

import hashlib
import sqlite3
from pathlib import Path

from alembic import op
from boxen.shared.values import new_id, now

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    root = Path(__file__).resolve().parents[4]
    source = (root / "assets/schema.sql").read_bytes()
    statement = ""
    for line in source.decode().splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql and not sql.startswith(("PRAGMA ", "BEGIN ", "COMMIT")):
                op.get_bind().exec_driver_sql(sql)
            statement = ""
    op.get_bind().exec_driver_sql(
        "INSERT INTO schema_migrations VALUES(?,?,?)", (revision, hashlib.sha256(source).hexdigest(), now())
    )
    import json

    op.get_bind().exec_driver_sql(
        "INSERT INTO app_settings VALUES(?,?,?)", ("installation_id", json.dumps(new_id()), now())
    )


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is not supported. Restore a verified pre-upgrade backup offline."
    )
