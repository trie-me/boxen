"""Disposable administration fixture; never reads or mutates live Boxen data."""

import json
import os
import tempfile
from pathlib import Path

import uvicorn
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.application import Application
from boxen.platform.config import Settings

with tempfile.TemporaryDirectory(prefix="boxen-admin-e2e-") as directory:
    providers_file = Path(directory) / "test-providers.json"
    providers_file.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "example",
                        "label": "Example ID",
                        "issuer": "https://identity.example.test",
                        "client_id": "boxen-test",
                        "enabled": True,
                    }
                ]
            }
        )
    )
    settings = Settings(
        env="test",
        origin="http://127.0.0.1:8176",
        anonymous_access="off",
        data_dir=Path(directory),
        oauth_providers_file=providers_file,
        disk_reserve_bytes=0,
        disk_reserve_percent=0,
        frontend_dir=Path(
            os.environ.get("BOXEN_TEST_FRONTEND_DIR", Path(__file__).resolve().parents[1] / "boxen/static")
        ),
    )
    token = initialize(settings)
    application = Application(settings)
    owner = application.execute(
        "createFirstOwner",
        {},
        {"username": "admin", "display_name": "Core Administrator", "password": "test-only-admin-password"},
        {"origin": settings.origin, "x-boxen-setup-token": token},
        None,
        "local",
        "fixture-owner",
        True,
    )
    application.execute(
        "createUser",
        {},
        {
            "username": "reader",
            "display_name": "Read Only",
            "role": "viewer",
            "password": "test-only-reader-password",
        },
        {"origin": settings.origin, "x-csrf-token": owner.body["csrf_token"]},
        owner.cookie,
        "local",
        "fixture-reader",
        True,
    )
    application.database.close()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8176, access_log=False)
