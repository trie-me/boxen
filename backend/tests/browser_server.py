"""Disposable loopback-only browser fixture; never a production startup path."""

import os
import tempfile
from pathlib import Path

import uvicorn
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.application import Application
from boxen.platform.config import Settings

settings = Settings(
    env="test",
    origin="http://127.0.0.1:8173",
    anonymous_access="viewer",  # Explicit read-only fixture; application default is editor.
    data_dir=Path(tempfile.mkdtemp(prefix="boxen-e2e-")),
    disk_reserve_bytes=0,
    disk_reserve_percent=0,
    frontend_dir=Path(
        os.environ.get("BOXEN_TEST_FRONTEND_DIR", Path(__file__).resolve().parents[1] / "boxen/static")
    ),
)
token = initialize(settings)
application = Application(settings)
application.execute(
    "createFirstOwner",
    {},
    {"username": "owner", "display_name": "Test Owner", "password": "test-only-long-passphrase"},
    {"origin": settings.origin, "x-boxen-setup-token": token},
    None,
    "local",
    "fixture",
    True,
)
application.database.close()
uvicorn.run(create_app(settings), host="127.0.0.1", port=8173, access_log=False)
