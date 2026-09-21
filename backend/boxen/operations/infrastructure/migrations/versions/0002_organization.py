"""STRICT tags and collections plus the expanded box search projection."""

import hashlib
import sqlite3

from alembic import op
from boxen.operations.infrastructure.migrate import ASSETS
from boxen.shared.values import now

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    source = (ASSETS / "migrations/0002_organization.sql").read_bytes()
    statement = ""
    for line in source.decode().splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        statement += line
        if sqlite3.complete_statement(statement):
            op.get_bind().exec_driver_sql(statement.strip())
            statement = ""
    if statement.strip():
        raise RuntimeError("Incomplete organization migration SQL.")
    op.get_bind().exec_driver_sql(
        "INSERT INTO schema_migrations VALUES(?,?,?)", (revision, hashlib.sha256(source).hexdigest(), now())
    )


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is not supported. Restore a verified pre-upgrade backup offline."
    )
