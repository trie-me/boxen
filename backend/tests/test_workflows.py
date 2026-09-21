import io
import uuid

from boxen.platform.contracts import api_contract, resolve, validate_payload
from PIL import Image
from pypdf import PdfReader


def create_box(client, name="Workshop tools"):
    response = client.post(
        "/api/v1/boxes",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "name": name,
            "description_markdown": "## Contents\nSpare **cables** and tools.\n<script>alert(1)</script>",
        },
    )
    assert response.status_code == 201, response.text
    return response


def test_catalog_search_and_stale_writes(client):
    response = create_box(client)
    box, tag = response.json(), response.headers["etag"]
    assert "<script>" not in box["description"]["html"]
    code = box["code"]
    assert client.get(f"/api/v1/boxes/{code}").json()["name"] == "Workshop tools"
    found = client.get("/api/v1/search", params={"q": "cables"})
    assert found.status_code == 200, found.text
    assert code in found.text
    changed = client.patch(f"/api/v1/boxes/{code}", headers={"If-Match": tag}, json={"name": "Garage tools"})
    assert changed.status_code == 200, changed.text
    stale = client.patch(f"/api/v1/boxes/{code}", headers={"If-Match": tag}, json={"name": "Stale name"})
    assert stale.status_code == 412, stale.text


def test_idempotency_and_csrf(client):
    key = str(uuid.uuid4())
    first = client.post("/api/v1/boxes", headers={"Idempotency-Key": key}, json={"name": "One box"})
    replay = client.post("/api/v1/boxes", headers={"Idempotency-Key": key}, json={"name": "One box"})
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert (
        client.post("/api/v1/boxes", headers={"Idempotency-Key": key}, json={"name": "Different"}).status_code
        == 409
    )
    assert (
        client.post("/api/v1/boxes", headers={"X-CSRF-Token": "wrong"}, json={"name": "Denied"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/boxes", headers={"Origin": "https://evil.invalid"}, json={"name": "Denied"}
        ).status_code
        == 403
    )


def test_inventory_media_pdf_and_resolve(client):
    box = create_box(client).json()
    code = box["code"]
    item = client.post(
        f"/api/v1/boxes/{code}/items",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "name": "USB-C adapter",
            "quantity": "2",
            "unit": "pieces",
            "notes_markdown": "For the blue monitor",
        },
    )
    assert item.status_code == 201, item.text
    assert code in client.get("/api/v1/search?q=adapter").text
    data = io.BytesIO()
    Image.new("RGB", (320, 240), "cyan").save(data, "JPEG")
    uploaded = client.post(
        f"/api/v1/boxes/{code}/images",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        files={"file": ("tools.jpg", data.getvalue(), "image/jpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert client.get(uploaded.json()["thumbnail_url"]).headers["content-type"] == "image/webp"
    profiles = client.get("/api/v1/label-profiles")
    assert profiles.status_code == 200, profiles.text
    for profile in profiles.json()["items"]:
        pdf = client.get(f"/api/v1/boxes/{code}/label.pdf", params={"profile": profile["key"]})
        assert pdf.status_code == 200, pdf.text[:200]
        reader = PdfReader(io.BytesIO(pdf.content))
        assert code in reader.pages[0].extract_text()
    result = client.post("/api/v1/codes/resolve", json={"input": "boxen:v1:" + code})
    assert result.status_code == 200, result.text
    assert result.json()["box"]["code"] == code


def test_response_contracts(client):
    create_box(client)
    contract = api_contract()
    for path in ("/boxes", "/session", "/system", "/label-profiles", "/users", "/backups"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 200, response.text
        schema = resolve(contract["paths"][path]["get"]["responses"]["200"])["content"]["application/json"][
            "schema"
        ]
        validate_payload(response.json(), schema)


def test_no_ai_does_not_disable_catalog(client):
    response = create_box(client)
    assert response.status_code == 201
    status = client.get("/api/v1/system").json()
    assert status["components"]["ai"]["status"] == "unavailable"
