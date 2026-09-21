import hashlib
import io
import uuid

import pytest
from boxen.catalog.domain import ALPHABET, BoxCode, resolve_payload
from boxen.catalog.infrastructure.markdown import markdown_columns
from boxen.platform.contracts import strict_json
from boxen.shared.errors import DomainError
from boxen.shared.values import quantity_milli, quantity_text
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image
from test_workflows import create_box


@given(st.text(alphabet=ALPHABET, min_size=7, max_size=7))
def test_code_round_trip(payload):
    code = BoxCode.from_payload(payload)
    assert BoxCode.parse(code.value.lower()).value == code.value
    assert resolve_payload(code.qr_payload, "https://boxen.local")[0] == code
    assert len(code.value) == 12


@pytest.mark.parametrize("raw", ["BX-7K3M-R9QB", "ＢX-7K3M-R9QA", "", "../etc/passwd", "BX-!!!!!!??"])
def test_bad_codes(raw):
    with pytest.raises(DomainError):
        BoxCode.parse(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://evil.test/boxes/BX-7K3M-R9QA",
        "boxen:v2:BX-7K3M-R9QA",
        "https://boxen.local/boxes/BX-7K3M-R9QA?track=1",
        "javascript:alert(1)",
    ],
)
def test_unsafe_payloads(raw):
    with pytest.raises(DomainError):
        resolve_payload(raw, "https://boxen.local")


@pytest.mark.parametrize("value", ["1", "0.001", "123.125", "1000", None])
def test_quantity_roundtrip(value):
    assert quantity_text(quantity_milli(value)) == value


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b"[" * 34 + b"0" + b"]" * 34])
def test_strict_json(raw):
    with pytest.raises(DomainError):
        strict_json(raw)


def test_sanitizer_blocks_active_and_remote_content():
    result = markdown_columns(
        "<script>alert(1)</script> ![tracking](https://evil.test/x) [click](javascript:alert(1))",
        "description",
    )
    assert "<script>" not in result["description_html"]
    assert "<img" not in result["description_html"]
    assert 'href="javascript:' not in result["description_html"]


def test_viewer_authorization_and_session_revocation(client):
    box = create_box(client).json()
    created = client.post(
        "/api/v1/users",
        json={
            "username": "viewer",
            "display_name": "Viewer",
            "role": "viewer",
            "password": "viewer-long-test-passphrase",
        },
    )
    assert created.status_code == 201, created.text
    viewer = client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "viewer-long-test-passphrase"}
    )
    assert viewer.status_code == 200
    client.headers["X-CSRF-Token"] = viewer.json()["csrf_token"]
    assert client.get("/api/v1/boxes/" + box["code"]).status_code == 200
    assert client.post("/api/v1/boxes", json={"name": "Denied"}).status_code == 403
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/backups").status_code == 403
    status = client.get("/api/v1/system").json()
    assert "storage" not in status["components"]
    assert "storage_free_bytes" not in status["limits"]
    # Reauthenticate owner; login deliberately revoked its previous cookie.
    owner = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "long-unique-test-passphrase"}
    )
    client.headers["X-CSRF-Token"] = owner.json()["csrf_token"]
    user = created.json()
    disabled = client.patch(
        "/api/v1/users/" + user["id"],
        headers={"If-Match": created.headers["etag"]},
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200, disabled.text
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": "viewer-long-test-passphrase"}
        ).status_code
        == 401
    )


def test_last_owner_and_request_boundaries(client):
    session = client.get("/api/v1/session")
    user = session.json()["user"]
    disabled = client.patch(
        "/api/v1/users/" + user["id"],
        headers={"If-Match": session.headers["etag"]},
        json={"status": "disabled"},
    )
    assert disabled.status_code == 409
    assert client.get("/api/v1/system", headers={"Host": "evil.test"}).status_code == 400
    assert (
        client.post(
            "/api/v1/boxes", content=b'{"name":"A","name":"B"}', headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.post("/api/v1/boxes", json={"name": "Box", "unknown": True}).status_code == 422
    assert client.get("/api/v1/boxes").headers["content-security-policy"].startswith("default-src 'self'")


def test_archive_restore_items_and_unsupported_upload(client):
    response = create_box(client)
    code = response.json()["code"]
    archived = client.post(f"/api/v1/boxes/{code}/archive", headers={"If-Match": response.headers["etag"]})
    assert archived.status_code == 200, archived.text
    assert (
        client.post(
            f"/api/v1/boxes/{code}/items",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"name": "Blocked"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/boxes/{code}", headers={"If-Match": archived.headers["etag"]}, json={"name": "Blocked"}
        ).status_code
        == 409
    )
    restored = client.post(f"/api/v1/boxes/{code}/restore", headers={"If-Match": archived.headers["etag"]})
    assert restored.status_code == 200
    invalid = client.post(
        f"/api/v1/boxes/{code}/images",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        files={"file": ("bad.jpg", b'<svg onload="alert(1)"/>', "image/jpeg")},
    )
    assert invalid.status_code == 422
    item = client.post(
        f"/api/v1/boxes/{code}/items",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"name": "Hammer", "quantity": "2"},
    )
    identifier = item.json()["id"]
    assert (
        client.delete("/api/v1/items/" + identifier, headers={"If-Match": item.headers["etag"]}).status_code
        == 204
    )
    assert "Hammer" not in client.get(f"/api/v1/boxes/{code}").text
    removed = client.get("/api/v1/items/" + identifier)
    assert (
        client.patch(
            "/api/v1/items/" + identifier,
            headers={"If-Match": removed.headers["etag"]},
            json={"lifecycle": "active"},
        ).status_code
        == 200
    )


def test_original_integrity_and_deduplication(client):
    box = create_box(client).json()
    image = io.BytesIO()
    Image.new("RGB", (60, 80), "blue").save(image, "PNG")

    def upload():
        return client.post(
            f"/api/v1/boxes/{box['code']}/images",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            files={"file": ("../../unsafe.png", image.getvalue(), "image/png")},
        )

    first, second = upload(), upload()
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["original_filename"] == "unsafe.png"
    original = client.get(f"/api/v1/images/{first.json()['id']}/content?variant=original")
    assert hashlib.sha256(original.content).hexdigest() == first.json()["sha256"]
