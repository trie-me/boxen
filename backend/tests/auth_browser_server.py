"""Disposable first-owner fixture; never opens the live data directory."""

import hashlib
import os
import tempfile
from pathlib import Path

import uvicorn
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import Database, initialize
from boxen.platform.config import Settings

with tempfile.TemporaryDirectory(prefix="boxen-auth-e2e-") as directory:
    settings = Settings(
        env="development",
        origin="http://boxen-auth.test:8175",
        anonymous_access="editor",
        data_dir=Path(directory),
        disk_reserve_bytes=0,
        disk_reserve_percent=0,
        frontend_dir=Path(
            os.environ.get("BOXEN_TEST_FRONTEND_DIR", Path(__file__).resolve().parents[1] / "boxen/static")
        ),
    )
    initialize(settings)
    database = Database(settings)
    with database.transaction(write=True) as repo:
        # Known test-only token makes actual browser bootstrap deterministic.
        repo.set_setting(
            "setup_token_hash", hashlib.sha256(("boxen-test-token-only-" + "x" * 32).encode()).hexdigest()
        )
    database.close()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8175, access_log=False)
