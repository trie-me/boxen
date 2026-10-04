"""Authentication store tests use disposable data directories and never deployed accounts."""

import fcntl
import hashlib
import secrets
import sqlite3

import pytest
from argon2.exceptions import VerificationError
from boxen.cli import administrative_application
from boxen.identity.application import HASHER, PEPPER_PREFIX, Identity
from boxen.identity.domain import ANONYMOUS_USER_ID
from boxen.operations.infrastructure.database import Database, initialize
from boxen.platform.application import Application
from boxen.shared.errors import DomainError
from boxen.shared.values import after, etag, new_id, now
from sqlalchemy.exc import IntegrityError
from test_organization_migration import v1_database

PASSWORD = "long-unique-test-passphrase"


def add_user(client, username="reader", role="viewer"):
    response = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": username.title(),
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_password_hash_has_unique_salt_and_separate_pepper(client):
    app = client.app.state.services
    other = add_user(client)
    with app.database.transaction() as repo:
        admin = repo.one("users", username="owner")
        second = repo.one("users", id=other["id"])
    assert admin["password_hash"].startswith(PEPPER_PREFIX + "$argon2id$")
    assert admin["password_hash"] != second["password_hash"]
    assert app.identity.verify_password(admin["password_hash"], PASSWORD)
    with pytest.raises(VerificationError):
        HASHER.verify(admin["password_hash"].removeprefix(PEPPER_PREFIX), PASSWORD)
    assert app.settings.password_pepper_file.stat().st_mode & 0o777 == 0o600
    assert app.settings.password_pepper() != app.settings.secret()
    assert len(app.settings.password_pepper()) == 32
    assert "password_hash" not in other and other["local_password"]
    assert client.get("/api/v1/session").json()["user"]["is_system_admin"]


@pytest.mark.parametrize("change", [{"status": "disabled"}, {"role": "viewer"}])
def test_core_admin_cannot_be_disabled_or_demoted_even_with_other_owners(client, change):
    add_user(client, "other-owner", "owner")
    admin = client.get("/api/v1/session").json()["user"]
    response = client.patch(
        "/api/v1/users/" + admin["id"],
        json=change,
        headers={"If-Match": etag("user", admin["id"], admin["version"])},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "user.system_admin_protected"
    with client.app.state.services.database.transaction(write=True) as repo:
        with pytest.raises(IntegrityError, match="core system administrator"):
            repo.update("users", {"role": "viewer"}, id=admin["id"])
        with pytest.raises(IntegrityError, match="cannot be deleted"):
            repo.delete("users", id=admin["id"])
        with pytest.raises(IntegrityError, match="local authentication only"):
            repo.insert(
                "external_identities",
                {
                    "id": new_id(),
                    "user_id": admin["id"],
                    "provider_id": "fixture",
                    "issuer": "https://id.test",
                    "subject": "subject",
                    "created_at": now(),
                },
            )


def test_legacy_password_upgrades_after_successful_login_and_preserves_core_id(settings):
    v1_database(settings)
    legacy_hash = HASHER.hash(PASSWORD)
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE users SET password_hash=? WHERE id='user'", (legacy_hash,))
    assert initialize(settings) is None
    app = Application(settings)
    try:
        with app.database.transaction(write=True) as repo:
            assert repo.one("users", id="user")["is_system_admin"] == 1
            rejected = app.identity.login(
                repo, {"username": "owner", "password": "wrong-password"}, "ip", new_id()
            )
            assert isinstance(rejected, DomainError)
            assert repo.one("users", id="user")["password_hash"] == legacy_hash
            result, token = app.identity.login(
                repo, {"username": "owner", "password": PASSWORD}, "ip", new_id()
            )
            upgraded = repo.one("users", id="user")
            assert upgraded["password_hash"].startswith(PEPPER_PREFIX)
            assert result["user"]["id"] == "user" and result["user"]["is_system_admin"]
            assert app.identity.authenticate(repo, token, new_id()).user["id"] == "user"
    finally:
        app.database.close()


def test_missing_pepper_is_never_recreated_and_wrong_pepper_fails_closed(client):
    app = client.app.state.services
    original = app.settings.password_pepper_file.read_bytes()
    app.settings.password_pepper_file.unlink()
    # Web runtime lock also protects initialization, so test the missing key after closing the client.
    with pytest.raises(RuntimeError, match="Password pepper is missing"):
        Identity(app.settings)
    app.settings.password_pepper_file.write_bytes(secrets.token_bytes(32))
    app.settings.password_pepper_file.chmod(0o600)
    with pytest.raises(DomainError, match="does not match"):
        Application(app.settings)
    app.settings.password_pepper_file.write_bytes(original)


def test_initialize_refuses_missing_previously_initialized_pepper(settings):
    initialize(settings)
    settings.password_pepper_file.unlink()
    with pytest.raises(RuntimeError, match="Restore the original pepper"):
        initialize(settings)
    assert not settings.password_pepper_file.exists()


def test_initialize_refuses_wrong_pepper_and_preserves_bytes(settings):
    initialize(settings)
    replacement = secrets.token_bytes(32)
    settings.password_pepper_file.write_bytes(replacement)
    with pytest.raises(RuntimeError, match="does not match"):
        initialize(settings)
    assert settings.password_pepper_file.read_bytes() == replacement


@pytest.mark.parametrize("mode,size", [(0o644, 32), (0o600, 31), (0o600, 33)])
def test_pepper_must_have_private_permissions_and_exact_length(settings, mode, size):
    initialize(settings)
    settings.password_pepper_file.write_bytes(b"x" * size)
    settings.password_pepper_file.chmod(mode)
    with pytest.raises(RuntimeError, match="Password pepper"):
        Identity(settings)


def test_session_inventory_redacts_secrets_and_supports_single_and_user_revocation(client):
    app = client.app.state.services
    reader = add_user(client)
    with app.database.transaction(write=True) as repo:
        user = repo.one("users", id=reader["id"])
        _, first = app.identity.start_session(repo, user, new_id())
        _, second = app.identity.start_session(repo, user, new_id(), "oidc")
    response = client.get("/api/v1/auth/sessions", params={"user_id": reader["id"]})
    assert response.status_code == 200, response.text
    sessions = response.json()["items"]
    assert len(sessions) == 2 and {row["method"] for row in sessions} == {"password", "oidc"}
    assert all(row["active"] and not row["current"] for row in sessions)
    assert first not in response.text and second not in response.text
    assert hashlib.sha256(first.encode()).hexdigest() not in response.text
    assert "csrf" not in response.text and "token_hash" not in response.text
    removed = client.delete("/api/v1/auth/sessions/" + sessions[0]["id"])
    assert removed.status_code == 204, removed.text
    revoked = client.post("/api/v1/users/" + reader["id"] + "/revoke-sessions")
    assert revoked.status_code == 200 and revoked.json() == {"revoked": 1}
    with app.database.transaction() as repo:
        for token in (first, second):
            with pytest.raises(DomainError):
                app.identity.authenticate(repo, token, new_id())
    assert client.get("/api/v1/session").status_code == 200


def test_session_inventory_observes_idle_expiration_and_stale_credentials(client):
    app = client.app.state.services
    reader = add_user(client)
    with app.database.transaction(write=True) as repo:
        user = repo.one("users", id=reader["id"])
        _, token = app.identity.start_session(repo, user, new_id())
        repo.update(
            "sessions",
            {"last_seen_at": after(-13 * 3600)},
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
    row = client.get("/api/v1/auth/sessions", params={"user_id": reader["id"]}).json()["items"][0]
    assert row["active"] is False


def test_auth_events_are_bounded_and_failed_credentials_are_redacted(client):
    app = client.app.state.services
    with app.database.transaction(write=True) as repo:
        result = app.identity.login(
            repo, {"username": "private-unknown-name", "password": "not-the-password"}, "ip", new_id()
        )
        assert isinstance(result, DomainError)
    response = client.get("/api/v1/auth/events", params={"limit": 1})
    assert response.status_code == 200, response.text
    events = response.json()["items"]
    assert len(events) == 1 and events[0]["action"] == "auth.login_failed"
    assert events[0]["user_id"] is None and events[0]["username"] is None
    assert events[0]["method"] == "password"
    assert "private-unknown-name" not in response.text and "not-the-password" not in response.text
    assert client.get("/api/v1/auth/events", params={"limit": 501}).status_code == 422


def test_nonowners_cannot_inspect_auth_store_and_revocation_needs_recent_login(client):
    app = client.app.state.services
    reader = add_user(client)
    admin_token = client.cookies.get("boxen_session")
    admin_session = client.get("/api/v1/auth/sessions").json()["items"][0]
    with app.database.transaction(write=True) as repo:
        repo.update(
            "sessions",
            {"created_at": after(-901)},
            token_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
        )
    denied = client.delete("/api/v1/auth/sessions/" + admin_session["id"])
    assert denied.status_code == 403 and denied.json()["code"] == "auth.reauthentication_required"
    login = client.post("/api/v1/auth/login", json={"username": reader["username"], "password": PASSWORD})
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.get("/api/v1/auth/sessions").status_code == 403
    assert client.get("/api/v1/auth/events").status_code == 403
    assert client.post("/api/v1/users/" + reader["id"] + "/revoke-sessions").status_code == 403


def test_offline_password_recovery_revokes_sessions_and_is_audited(client):
    app = client.app.state.services
    token = client.cookies.get("boxen_session")
    with app.database.transaction(write=True) as repo:
        admin = app.identity.reset_admin_password(repo, "new-unique-recovery-password", new_id())
        assert admin["is_system_admin"] and admin["local_password"]
        with pytest.raises(DomainError):
            app.identity.authenticate(repo, token, new_id())
        assert repo.find("audit_log", action="user.password_reset")
        assert app.identity.verify_password(
            repo.one("users", id=admin["id"])["password_hash"], "new-unique-recovery-password"
        )


def test_offline_recovery_cannot_cross_running_service_lock(settings):
    initialize(settings)
    with (settings.data_dir / "db/runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(DomainError, match="Stop services"):
            with administrative_application(settings, "admin-password"):
                pytest.fail("Offline recovery acquired a lock while a service was running")


def test_anonymous_only_installation_can_initialize_setup_token(settings):
    initialize(settings)
    settings.anonymous_access = "viewer"
    identity = Identity(settings)
    database = Database(settings)
    try:
        with database.transaction(write=True) as repo:
            identity.start_anonymous_session(repo, new_id())
            repo.delete("app_settings", key="setup_token_hash")
        assert initialize(settings)
        with database.transaction() as repo:
            assert repo.one("users", id=ANONYMOUS_USER_ID)["is_system_admin"] == 0
    finally:
        database.close()


def test_restore_preserves_custom_pepper_without_archiving_it_and_clears_oidc_state(settings):
    settings.password_pepper_file = settings.data_dir / "private/credential.pepper"
    initialize(settings)
    app = Application(settings)
    original_pepper = settings.password_pepper()
    try:
        with app.database.transaction(write=True) as repo:
            installation = repo.setting("installation_id")
            repo.insert(
                "oidc_transactions",
                {
                    "state_hash": "state",
                    "provider_id": "example",
                    "browser_hash": "browser",
                    "nonce": "nonce",
                    "code_verifier": "verifier",
                    "redirect_uri": "https://boxen.test/callback",
                    "created_at": now(),
                    "expires_at": after(300),
                },
            )
        row = {"relative_path": "auth-restore"}
        app.backups.create(row)
        path = app.backups.path(row)
        manifest = app.backups.verify(path)
        assert not any("pepper" in name or name.startswith("secrets/") for name in manifest["files"])
        app.backups.restore(path, installation, apply=True)
        assert settings.password_pepper() == original_pepper
        restored = Database(settings)
        try:
            with restored.transaction() as repo:
                assert repo.find("oidc_transactions") == []
                Identity(settings).validate_password_pepper(repo)
        finally:
            restored.close()
    finally:
        app.database.close()


def test_restore_rejects_pepper_from_different_installation_before_changes(settings):
    initialize(settings)
    app = Application(settings)
    try:
        with app.database.transaction() as repo:
            installation = repo.setting("installation_id")
        row = {"relative_path": "pepper-mismatch"}
        app.backups.create(row)
        settings.password_pepper_file.write_bytes(secrets.token_bytes(32))
        with pytest.raises(DomainError, match="pepper belonging to this backup"):
            app.backups.restore(app.backups.path(row), installation, apply=True)
        assert not list(settings.data_dir.parent.glob("data.quarantine-*"))
        assert not list(settings.data_dir.parent.glob("data.restore-*"))
    finally:
        app.database.close()


def test_admin_idempotency_receipts_require_current_owner_role(client):
    second = add_user(client, "second-owner", "owner")
    session = client.post(
        "/api/v1/auth/login", json={"username": "second-owner", "password": PASSWORD}
    ).json()
    client.headers["X-CSRF-Token"] = session["csrf_token"]
    key = new_id()
    request = {
        "username": "managed-reader",
        "display_name": "Managed Reader",
        "role": "viewer",
        "password": PASSWORD,
    }
    response = client.post("/api/v1/users", json=request, headers={"Idempotency-Key": key})
    assert response.status_code == 201
    # The core owner demotes the other owner. Its known retry key must not grant access afterward.
    owner = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}).json()
    client.headers["X-CSRF-Token"] = owner["csrf_token"]
    assert (
        client.patch(
            "/api/v1/users/" + second["id"],
            json={"role": "viewer"},
            headers={"If-Match": etag("user", second["id"], second["version"])},
        ).status_code
        == 200
    )
    viewer = client.post("/api/v1/auth/login", json={"username": "second-owner", "password": PASSWORD}).json()
    client.headers["X-CSRF-Token"] = viewer["csrf_token"]
    assert client.post("/api/v1/users", json=request, headers={"Idempotency-Key": key}).status_code == 403
