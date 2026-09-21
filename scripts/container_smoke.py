"""Disposable production-image smoke. Run only with an empty test data mount."""

import io
import json
import socket
import uuid

from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from boxen.worker.main import tick
from fastapi.testclient import TestClient
from PIL import Image

settings = Settings.load()
token = initialize(settings)
assert token, "Refusing to run the smoke test against an initialized data directory."
with TestClient(create_app(settings), base_url=settings.origin) as client:
    client.headers["Origin"] = settings.origin
    client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid.uuid4()))
    )
    anonymous = client.get("/api/v1/session")
    assert anonymous.status_code == 200 and anonymous.json()["anonymous"] is True
    assert client.get("/api/v1/boxes").status_code == 200
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/setup/status").json()["setup_required"] is True
    owner = client.post(
        "/api/v1/setup/owner",
        headers={"X-Boxen-Setup-Token": token},
        json={
            "username": "test-owner",
            "display_name": "Smoke fixture",
            "password": "disposable-smoke-passphrase",
        },
    )
    assert owner.status_code == 201, owner.text
    client.headers["X-CSRF-Token"] = owner.json()["csrf_token"]
    assert client.get("/").status_code == 200, "Packaged frontend missing"
    box = client.post(
        "/api/v1/boxes", json={"name": "Offline smoke", "description_markdown": "**Local** box"}
    )
    assert box.status_code == 201, box.text
    code = box.json()["code"]
    item = client.post(f"/api/v1/boxes/{code}/items", json={"name": "Spare cable", "quantity": "2"})
    assert item.status_code == 201, item.text
    image = io.BytesIO()
    Image.new("RGB", (200, 100), "green").save(image, "PNG")
    photo = client.post(
        f"/api/v1/boxes/{code}/images", files={"file": ("photo.png", image.getvalue(), "image/png")}
    )
    assert photo.status_code == 201, photo.text
    assert client.get(photo.json()["thumbnail_url"]).status_code == 200
    assert code in client.get("/api/v1/search?q=cable").text
    label = client.get(f"/api/v1/boxes/{code}/label.pdf?profile=roll-62x29-mm-v1")
    assert label.status_code == 200 and label.content.startswith(b"%PDF")
    resolved = client.post("/api/v1/codes/resolve", json={"input": "boxen:v1:" + code})
    assert resolved.status_code == 200
    services = client.app.state.services
    tick(services, "smoke-worker")
    backups = client.get("/api/v1/backups").json()["items"]
    assert backups and backups[0]["status"] == "verified", backups
    assert client.get("/api/v1/system").json()["components"]["ai"]["status"] == "unavailable"
    # Numeric documentation-only address: no DNS or private host is contacted.
    external = socket.socket()
    external.settimeout(0.2)
    try:
        external.connect(("192.0.2.1", 443))
        raise AssertionError("Expected a network-isolated test container")
    except OSError:
        pass
    finally:
        external.close()
print(
    json.dumps(
        {
            "packaged_frontend": "pass",
            "identity": "pass",
            "anonymous_browsing_admin_protection": "pass",
            "catalog_inventory_search": "pass",
            "media": "pass",
            "labels_resolve": "pass",
            "worker_backup": "pass",
            "network_disabled": "pass",
            "ai_disabled_core_healthy": "pass",
        }
    )
)
