import hashlib
import uuid

import pytest
from boxen.api.app import create_app
from boxen.identity.application import HASHER
from boxen.identity.domain import ANONYMOUS_USER_ID, ANONYMOUS_USERNAME
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from boxen.shared.values import after
from conftest import check_response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_workflows import create_box


def browser(app, origin):
    client = TestClient(app, base_url=origin)
    client.headers["Origin"] = origin
    client.event_hooks["response"].append(check_response)
    client.event_hooks["request"].append(
        lambda request: (
            request.headers.setdefault("Idempotency-Key", str(uuid.uuid4()))
            if request.method not in {"GET", "HEAD"}
            else None
        )
    )
    return client


def session(client):
    response = client.get("/api/v1/session")
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


@pytest.fixture
def anonymous_client(settings):
    settings.anonymous_access = "viewer"
    initialize(settings)
    with browser(create_app(settings), settings.origin) as client:
        yield client


def test_anonymous_configuration_defaults_and_environment(monkeypatch):
    assert Settings().anonymous_access == "editor"
    for mode in ("off", "viewer", "editor"):
        monkeypatch.setenv("BOXEN_ANONYMOUS_ACCESS", mode)
        assert Settings.load().anonymous_access == mode
    monkeypatch.setenv("BOXEN_ANONYMOUS_ACCESS", "owner")
    with pytest.raises(ValidationError):
        Settings.load()


def test_no_login_reads_default_viewer(client, settings):
    box = create_box(client)
    settings.anonymous_access = "viewer"
    with browser(client.app, settings.origin) as visitor:
        assert visitor.get("/api/v1/boxes").status_code == 401
        first = session(visitor)
        assert first.json()["anonymous"] is True
        assert first.json()["user"]["role"] == "viewer"
        assert first.json()["capabilities"] == ["box.read", "search", "scan"]
        cookie = visitor.cookies.get("boxen_session")
        assert cookie and "HttpOnly" in first.headers["set-cookie"]
        assert "SameSite=strict" in first.headers["set-cookie"]
        assert first.headers["cache-control"] == "no-store"
        again = session(visitor)
        assert again.json() == first.json()
        assert again.headers["etag"] == first.headers["etag"]
        assert "set-cookie" not in again.headers
        assert visitor.cookies.get("boxen_session") == cookie
        assert visitor.get("/api/v1/boxes").json()["items"][0]["code"] == box.json()["code"]
        detail = visitor.get("/api/v1/boxes/" + box.json()["code"])
        assert detail.status_code == 200
        assert detail.headers["etag"] == box.headers["etag"]
        assert box.json()["code"] in visitor.get("/api/v1/search?q=cables").text
        status = visitor.get("/api/v1/system")
        assert status.status_code == 200
        assert "storage" not in status.json()["components"]
        assert "storage_free_bytes" not in status.json()["limits"]
        denied = visitor.post("/api/v1/boxes", json={"name": "Denied"})
        assert denied.status_code == 403
        assert denied.json()["code"] == "auth.forbidden"


def test_editor_requires_browser_csrf_origin_and_etags(anonymous_client, settings):
    settings.anonymous_access = "editor"
    client = anonymous_client
    current = session(client)
    assert "box.edit" in current.json()["capabilities"]
    del client.headers["X-CSRF-Token"]
    missing = client.post("/api/v1/boxes", json={"name": "Denied"})
    assert missing.status_code == 403
    assert missing.json()["code"] == "auth.csrf_invalid"
    client.headers["X-CSRF-Token"] = current.json()["csrf_token"]
    with browser(client.app, settings.origin) as other:
        other_session = session(other)
        assert other.cookies.get("boxen_session") != client.cookies.get("boxen_session")
        assert other_session.json()["csrf_token"] != current.json()["csrf_token"]
        assert other_session.json()["user"]["id"] == current.json()["user"]["id"]
        denied = client.post(
            "/api/v1/boxes",
            headers={"X-CSRF-Token": other_session.json()["csrf_token"]},
            json={"name": "Denied"},
        )
        assert denied.status_code == 403
        for origin in ("https://evil.invalid", "null", ""):
            denied = client.post("/api/v1/boxes", headers={"Origin": origin}, json={"name": "Denied"})
            assert denied.status_code == 403
            assert denied.json()["code"] == "auth.origin_invalid"
        created = create_box(client)
        url = "/api/v1/boxes/" + created.json()["code"]
        assert client.patch(url, json={"name": "Missing version"}).status_code == 428
        changed = client.patch(url, headers={"If-Match": created.headers["etag"]}, json={"name": "Edited"})
        assert changed.status_code == 200, changed.text
        stale = client.patch(url, headers={"If-Match": created.headers["etag"]}, json={"name": "Stale"})
        assert stale.status_code == 412
        with client.app.state.services.database.transaction() as repo:
            stored = repo.one("boxes", public_code=created.json()["code"])
            assert stored["created_by"] == stored["updated_by"] == ANONYMOUS_USER_ID
            assert repo.rows("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_anonymous_cannot_administer_backup_or_purge(anonymous_client, settings, role):
    settings.anonymous_access = role
    client = anonymous_client
    current = session(client)
    assert not {"users.manage", "system.manage", "backup.manage", "box.purge"}.intersection(
        current.json()["capabilities"]
    )
    identifier = str(uuid.uuid4())
    operations = [
        ("GET", "/users", None),
        ("GET", "/users/" + identifier, None),
        (
            "POST",
            "/users",
            {
                "username": "new-owner",
                "display_name": "Owner",
                "role": "owner",
                "password": "long-unique-test-passphrase",
            },
        ),
        ("PATCH", "/users/" + ANONYMOUS_USER_ID, {"role": "owner"}),
        ("GET", "/backups", None),
        ("POST", "/backups", None),
        ("GET", "/backups/" + identifier, None),
        ("POST", "/backups/" + identifier + "/verify", None),
        ("POST", "/maintenance/search/verify", None),
        ("POST", "/maintenance/search/rebuild", None),
        ("POST", "/maintenance/media/verify", None),
        ("GET", "/maintenance/" + identifier, None),
        ("POST", "/boxes/BX-7K3M-R9QA/purge", {"confirmation_code": "BX-7K3M-R9QA"}),
    ]
    for method, path, body in operations:
        response = client.request(
            method, "/api/v1" + path, headers={"If-Match": current.headers["etag"]}, json=body
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "auth.forbidden"


def test_reserved_principal_has_no_profile_password_or_login(anonymous_client):
    client = anonymous_client
    current = session(client)
    assert current.json()["user"]["id"] == ANONYMOUS_USER_ID
    profile = client.patch(
        "/api/v1/session/profile",
        headers={"If-Match": current.headers["etag"]},
        json={"display_name": "Changed"},
    )
    assert profile.status_code == 403
    password = client.post(
        "/api/v1/session/password",
        json={"current_password": "anonymous", "new_password": "long-unique-test-passphrase"},
    )
    assert password.status_code == 403
    with client.app.state.services.database.transaction(write=True) as repo:
        principal = repo.one("users", id=ANONYMOUS_USER_ID)
        assert principal["password_hash"].startswith("!")
        # A valid hash still cannot turn this reserved identity into a login account.
        repo.update("users", {"password_hash": HASHER.hash("known-test-passphrase")}, id=ANONYMOUS_USER_ID)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": ANONYMOUS_USERNAME.upper(), "password": "known-test-passphrase"},
    )
    assert login.status_code == 401
    assert login.json()["code"] == "auth.invalid_credentials"
    assert session(client).json()["anonymous"] is True


def test_first_owner_bootstraps_after_anonymous_and_protects_reserved_user(anonymous_client, settings):
    client = anonymous_client
    visitor = session(client)
    old_cookie = client.cookies.get("boxen_session")
    services = client.app.state.services
    assert client.get("/api/v1/setup/status").json() == {"setup_required": True}
    token = (settings.data_dir / "secrets/setup-token").read_text()
    body = {"username": "owner", "display_name": "Owner", "password": "long-unique-test-passphrase"}
    denied = client.post("/api/v1/setup/owner", headers={"X-Boxen-Setup-Token": "x" * 43}, json=body)
    assert denied.status_code == 403
    created = client.post("/api/v1/setup/owner", headers={"X-Boxen-Setup-Token": token}, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["anonymous"] is False
    assert created.json()["user"]["role"] == "owner"
    assert client.cookies.get("boxen_session") != old_cookie
    assert client.get("/api/v1/setup/status").json() == {"setup_required": False}
    assert not (settings.data_dir / "secrets/setup-token").exists()
    owner_session = session(client)
    assert owner_session.json() == created.json()
    assert "set-cookie" not in owner_session.headers
    assert client.get("/api/v1/users").json()["items"] == [created.json()["user"]]
    assert client.get("/api/v1/users/" + ANONYMOUS_USER_ID).status_code == 404
    for changes in (
        {"role": "owner"},
        {"status": "disabled"},
        {"password": body["password"]},
        {"display_name": "Renamed"},
    ):
        updated = client.patch(
            "/api/v1/users/" + ANONYMOUS_USER_ID,
            headers={"If-Match": visitor.headers["etag"]},
            json=changes,
        )
        assert updated.status_code == 403, updated.text
    reserved = client.post("/api/v1/users", json={**body, "username": ANONYMOUS_USERNAME, "role": "owner"})
    assert reserved.status_code == 409
    assert reserved.json()["code"] == "user.reserved"
    again = client.post("/api/v1/setup/owner", headers={"X-Boxen-Setup-Token": token}, json=body)
    assert again.status_code == 409
    with services.database.transaction() as repo:
        assert repo.one("sessions", token_hash=hashlib.sha256(old_cookie.encode()).hexdigest())["revoked_at"]
        assert len(repo.find("users")) == 2


def test_idempotency_isolated_between_browsers_and_role_changes(anonymous_client, settings):
    client = anonymous_client
    settings.anonymous_access = "editor"
    session(client)
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}
    body = {"name": "Separate browser boxes"}
    first = client.post("/api/v1/boxes", headers=headers, json=body)
    assert first.status_code == 201
    replay = client.post("/api/v1/boxes", headers=headers, json=body)
    assert replay.status_code == 201 and replay.json() == first.json()
    conflict = client.post("/api/v1/boxes", headers=headers, json={"name": "Conflicting retry"})
    assert conflict.status_code == 409
    with browser(client.app, settings.origin) as other:
        session(other)
        separate = other.post("/api/v1/boxes", headers=headers, json=body)
        assert separate.status_code == 201, separate.text
        assert separate.json()["code"] != first.json()["code"]
        assert len(other.get("/api/v1/boxes").json()["items"]) == 2
        settings.anonymous_access = "viewer"
        assert session(client).json()["user"]["role"] == "viewer"
        denied = client.post("/api/v1/boxes", headers=headers, json=body)
        assert denied.status_code == 403


def test_role_is_from_configuration_and_off_rejects_existing_anonymous_sessions(anonymous_client, settings):
    client = anonymous_client
    current = session(client)
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.update("users", {"role": "owner"}, id=ANONYMOUS_USER_ID)
    assert session(client).json()["user"]["role"] == "viewer"
    assert client.get("/api/v1/users").status_code == 403
    settings.anonymous_access = "editor"
    assert session(client).json()["user"]["role"] == "editor"
    settings.anonymous_access = "off"
    assert client.get("/api/v1/session").status_code == 401
    assert client.get("/api/v1/boxes").status_code == 401
    assert client.post("/api/v1/boxes", json={"name": "Denied"}).status_code == 401
    client.cookies.clear()
    assert client.get("/api/v1/session").status_code == 401
    assert current.json()["anonymous"] is True


@pytest.mark.parametrize("invalidity", ["unknown", "expired", "idle", "revoked"])
def test_get_session_replaces_invalid_cookie(anonymous_client, invalidity):
    client = anonymous_client
    first = session(client)
    cookie = client.cookies.get("boxen_session")
    with client.app.state.services.database.transaction(write=True) as repo:
        token_hash = hashlib.sha256(cookie.encode()).hexdigest()
        if invalidity == "unknown":
            repo.delete("sessions", token_hash=token_hash)
        else:
            column = {"expired": "expires_at", "idle": "last_seen_at", "revoked": "revoked_at"}[invalidity]
            repo.update("sessions", {column: after(-86400)}, token_hash=token_hash)
    assert client.get("/api/v1/boxes").status_code == 401
    replacement = session(client)
    assert replacement.json()["anonymous"] is True
    assert replacement.json()["csrf_token"] != first.json()["csrf_token"]
    assert client.cookies.get("boxen_session") != cookie
    assert client.get("/api/v1/boxes").status_code == 200


def test_logout_revokes_only_current_browser_and_rebootstraps(anonymous_client, settings):
    client = anonymous_client
    first = session(client)
    old_cookie = client.cookies.get("boxen_session")
    with browser(client.app, settings.origin) as other:
        other_session = session(other)
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.cookies.get("boxen_session") is None
        assert client.get("/api/v1/boxes").status_code == 401
        assert session(other).json() == other_session.json()
        replacement = session(client)
        assert replacement.json()["csrf_token"] != first.json()["csrf_token"]
        with client.app.state.services.database.transaction() as repo:
            assert repo.one("sessions", token_hash=hashlib.sha256(old_cookie.encode()).hexdigest())[
                "revoked_at"
            ]
            assert len(repo.find("users")) == 1


def test_session_bootstrap_preserves_host_origin_and_secure_cookie(settings):
    settings.anonymous_access = "viewer"
    settings.origin = "https://boxen.local"
    initialize(settings)
    with browser(create_app(settings), settings.origin) as client:
        assert client.get("/api/v1/session", headers={"Host": "evil.invalid"}).status_code == 400
        assert client.get("/api/v1/session", headers={"Origin": "https://evil.invalid"}).status_code == 403
        assert client.cookies.get("boxen_session") is None
        with client.app.state.services.database.transaction() as repo:
            assert not repo.find("users")
            assert not repo.find("sessions")
        del client.headers["Origin"]
        current = session(client)
        assert "Secure" in current.headers["set-cookie"]
        assert "HttpOnly" in current.headers["set-cookie"]
        assert "SameSite=strict" in current.headers["set-cookie"]


def test_local_login_replaces_anonymous_session(client, settings):
    settings.anonymous_access = "viewer"
    client.cookies.clear()
    session(client)
    old_cookie = client.cookies.get("boxen_session")
    logged_in = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "long-unique-test-passphrase"}
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["anonymous"] is False
    assert logged_in.json()["user"]["role"] == "owner"
    assert client.cookies.get("boxen_session") != old_cookie
    assert session(client).json() == logged_in.json()
    with client.app.state.services.database.transaction() as repo:
        assert repo.one("sessions", token_hash=hashlib.sha256(old_cookie.encode()).hexdigest())["revoked_at"]
