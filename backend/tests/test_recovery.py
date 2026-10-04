import io
from pathlib import Path

from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.operations.infrastructure.migrate import CURRENT_SCHEMA_VERSION
from boxen.platform.application import Application
from boxen.shared.values import new_id
from fastapi.testclient import TestClient
from PIL import Image
from test_workflows import create_box


def test_restore_roundtrip_preserves_source_and_revokes_sessions(settings):
    token = initialize(settings)
    with TestClient(create_app(settings)) as client:
        client.headers["Origin"] = settings.origin
        response = client.post(
            "/api/v1/setup/owner",
            headers={"X-Boxen-Setup-Token": token},
            json={"username": "owner", "display_name": "Owner", "password": "restore-test-passphrase"},
        )
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        box = create_box(client).json()
        services = client.app.state.services
        requested = client.post("/api/v1/backups", headers={"Idempotency-Key": new_id()})
        assert requested.status_code == 202, requested.text
        services.operations.run_once()
        with services.database.transaction() as repo:
            backup = repo.one("backups", id=requested.json()["id"])
            installation = repo.setting("installation_id")
        path = services.backups.path(backup)
        original_cookie = client.cookies.get("boxen_session")
        modified = client.patch(
            "/api/v1/boxes/" + box["code"],
            headers={"If-Match": f'"box:{box["code"]}:v1"'},
            json={"name": "Changed after backup"},
        )
        assert modified.status_code == 200
    offline = Application(settings)
    outcome = offline.backups.restore(path, installation, apply=True)
    assert Path(outcome["quarantine"]).is_dir()
    with TestClient(create_app(settings)) as restored:
        restored.headers["Origin"] = settings.origin
        restored.cookies.set("boxen_session", original_cookie)
        assert restored.get("/api/v1/session").status_code == 401
        restored.cookies.clear()
        login = restored.post(
            "/api/v1/auth/login", json={"username": "owner", "password": "restore-test-passphrase"}
        )
        assert login.status_code == 200, login.text
        assert restored.get("/api/v1/boxes/" + box["code"]).json()["name"] == box["name"]


def test_upload_failure_reconciles_orphan_without_losing_referenced_objects(client, monkeypatch):
    box = create_box(client).json()
    app = client.app.state.services
    image = io.BytesIO()
    Image.new("RGB", (50, 50), "orange").save(image, "PNG")
    original_commit = app.media.store.commit
    calls = 0

    def fail_derivative(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected disk failure")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(app.media.store, "commit", fail_derivative)
    result = client.post(
        "/api/v1/boxes/" + box["code"] + "/images",
        files={"file": ("photo.png", image.getvalue(), "image/png")},
    )
    assert result.status_code == 500
    with app.database.transaction() as repo:
        assert repo.find("box_images") == []
    recovery = app.media.reconcile(grace_seconds=0)
    assert recovery["objects_quarantined"] == 1
    assert len(list((app.settings.data_dir / "media/quarantine").rglob("*.webp"))) == 1


def test_schema_is_locked_and_initialization_is_idempotent(settings):
    token = initialize(settings)
    assert token and initialize(settings) is None
    app = Application(settings)
    with app.database.transaction() as repo:
        assert repo.execute("PRAGMA journal_mode").scalar() == "wal"
        assert repo.execute("PRAGMA foreign_keys").scalar() == 1
        assert repo.execute("PRAGMA integrity_check").scalar() == "ok"
        assert repo.execute("SELECT version_num FROM alembic_version").scalar() == CURRENT_SCHEMA_VERSION
    app.database.close()
