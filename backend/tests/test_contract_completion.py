import io
import subprocess
import uuid

import pytest
import zxingcpp
from boxen.platform.contracts import api_contract
from PIL import Image
from test_ai_operations import analysis_fixture
from test_workflows import create_box

PRIVATE_OPERATIONS = [
    (method, path)
    for path, methods in api_contract()["paths"].items()
    for method, op in methods.items()
    if method in {"get", "post", "put", "patch", "delete"}
    and op["operationId"]
    not in {"getSetupStatus", "createFirstOwner", "login", "getLiveness", "getReadiness"}
]


@pytest.mark.parametrize("method,path", PRIVATE_OPERATIONS)
def test_every_private_api_requires_session(client, method, path):
    client.cookies.clear()
    import re

    url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
    response = client.request(method.upper(), "/api/v1" + url)
    assert response.status_code == 401, (method, path, response.text)


def test_user_profile_password_rotation_and_logout(client):
    for path in ["/setup/status", "/health/live", "/health/ready"]:
        assert client.get("/api/v1" + path).status_code == 200
    session = client.get("/api/v1/session")
    user = session.json()["user"]
    assert client.get("/api/v1/users/" + user["id"]).status_code == 200
    updated = client.patch(
        "/api/v1/session/profile",
        headers={"If-Match": session.headers["etag"]},
        json={"display_name": "Updated owner"},
    )
    assert updated.status_code == 200, updated.text
    changed = client.post(
        "/api/v1/session/password",
        json={
            "current_password": "long-unique-test-passphrase",
            "new_password": "another-long-test-passphrase",
        },
    )
    assert changed.status_code == 200, changed.text
    client.headers["X-CSRF-Token"] = changed.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/session").status_code == 401


def test_image_caption_order_removal_and_item_merge(client):
    box = create_box(client).json()
    code = box["code"]
    ids = []
    for color in ["red", "blue"]:
        buffer = io.BytesIO()
        Image.new("RGB", (80, 60), color).save(buffer, "PNG")
        photo = client.post(
            "/api/v1/boxes/" + code + "/images", files={"file": ("test.png", buffer.getvalue(), "image/png")}
        )
        ids.append(photo.json()["id"])
    images = client.get("/api/v1/boxes/" + code + "/images")
    assert len(images.json()["items"]) == 2
    ordered = client.put(
        "/api/v1/boxes/" + code + "/image-order",
        headers={"If-Match": images.headers["etag"]},
        json={"image_ids": list(reversed(ids))},
    )
    assert ordered.status_code == 200, ordered.text
    photo = client.get("/api/v1/images/" + ids[0])
    updated = client.patch(
        "/api/v1/images/" + ids[0], headers={"If-Match": photo.headers["etag"]}, json={"caption": "Blue tray"}
    )
    assert updated.status_code == 200, updated.text
    assert (
        client.delete("/api/v1/images/" + ids[0], headers={"If-Match": updated.headers["etag"]}).status_code
        == 204
    )
    a = client.post(
        "/api/v1/boxes/" + code + "/items", json={"name": "Screws", "quantity": "2", "unit": "pieces"}
    )
    b = client.post(
        "/api/v1/boxes/" + code + "/items", json={"name": "More screws", "quantity": "3", "unit": "pieces"}
    )
    merged = client.post(
        "/api/v1/items/merge",
        json={
            "survivor_id": a.json()["id"],
            "merged_item_ids": [b.json()["id"]],
            "survivor_etag": a.headers["etag"],
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["quantity"] == "5"
    assert len(client.get("/api/v1/boxes/" + code + "/items").json()["items"]) == 1


def test_observation_reject_and_merge_evidence(client):
    app, fake, box, photo, requested = analysis_fixture(client)
    fake.output["observations"].append({**fake.output["observations"][0], "name": "Duplicate wrench"})
    app.analysis.execute(app.analysis.claim("worker"))
    observations = client.get("/api/v1/boxes/" + box["code"] + "/observations").json()["items"]
    item = client.post("/api/v1/boxes/" + box["code"] + "/items", json={"name": "Wrench", "quantity": "1"})
    merge = client.post(
        "/api/v1/observations/" + observations[0]["id"] + "/accept",
        json={"mode": "merge", "item_id": item.json()["id"], "item_etag": item.headers["etag"]},
    )
    assert merge.status_code == 200, merge.text
    assert merge.json()["item"]["quantity"] == "1"
    assert merge.json()["item"]["provenance"] == "mixed"
    reject = client.post(
        "/api/v1/observations/" + observations[1]["id"] + "/reject", json={"reason": "duplicate"}
    )
    assert reject.status_code == 200, reject.text


def test_backup_reverify_and_media_maintenance(client):
    app = client.app.state.services
    backup = client.post("/api/v1/backups").json()
    assert app.operations.run_once()
    assert client.post("/api/v1/backups/" + backup["id"] + "/verify").status_code == 202
    assert app.operations.run_once()
    job = client.post("/api/v1/maintenance/media/verify")
    assert job.status_code == 202, job.text
    assert app.operations.run_once()
    assert client.get("/api/v1/maintenance/" + job.json()["id"]).json()["result"]["missing_originals"] == 0


@pytest.mark.parametrize("profile", ["roll-62x29-mm-v1", "sheet-4x2-in-v1", "sheet-a4-2x7-v1"])
def test_actual_pdf_raster_decodes_at_203dpi(client, tmp_path, profile):
    box = create_box(client, "Workshop / precision tools and adapters").json()
    response = client.get(
        "/api/v1/boxes/" + box["code"] + "/label.pdf",
        params={"profile": profile},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    pdf = tmp_path / "label.pdf"
    pdf.write_bytes(response.content)
    subprocess.run(
        ["pdftoppm", "-r", "203", "-f", "1", "-singlefile", "-png", str(pdf), str(tmp_path / "label")],
        check=True,
        capture_output=True,
    )
    with Image.open(tmp_path / "label.png") as image:
        decoded = zxingcpp.read_barcodes(image)
    assert decoded and all(code.text == "boxen:v1:" + box["code"] for code in decoded)
    assert len(decoded) == (14 if profile == "sheet-a4-2x7-v1" else 1)
