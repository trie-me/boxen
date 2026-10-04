import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from boxen.api.app import create_app
from boxen.identity.oauth import MAX_RESPONSE_BYTES, OIDC, digest, load_providers
from boxen.operations.infrastructure.database import initialize
from boxen.shared.values import after
from conftest import SUCCESSES, check_response
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

ISSUER = "https://identity.example.test"
PASSWORD = "long-unique-test-passphrase"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class Environment:
    client: TestClient
    service: OIDC
    owner: dict
    user: dict
    csrf: str
    key: object
    metadata: dict
    requests: list
    claims_patch: dict
    missing_claims: list
    nonce: str = ""
    token_override: str | None = None
    jwks_override: object = None
    status: int = 200

    def transport(self, request):
        self.requests.append(request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(self.status, json=self.metadata)
        if request.url.path == "/keys":
            if self.jwks_override is not None:
                return httpx.Response(200, json=self.jwks_override)
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(
                200, json={"keys": [{**key, "kid": "signing", "use": "sig", "alg": "RS256"}]}
            )
        assert request.url.path == "/token"
        claims = {
            "iss": ISSUER,
            "sub": "provider-subject",
            "aud": "boxen-client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "auth_time": int(time.time()),
            "nonce": self.nonce,
            **self.claims_patch,
        }
        for name in self.missing_claims:
            claims.pop(name)
        token = self.token_override or jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": "signing"}
        )
        return httpx.Response(
            200,
            json={
                "id_token": token,
                "access_token": "never-persist-me",
                "refresh_token": "never-persist-refresh",
            },
        )

    def start(self):
        response = self.client.post("/api/v1/auth/oidc/example/start", json={})
        assert response.status_code == 200, response.text
        query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
        self.nonce = query["nonce"][0]
        return query

    def callback(self, query, **extra):
        return self.client.get(
            "/api/v1/auth/oidc/example/callback?"
            + urlencode(
                {
                    "state": query["state"][0],
                    "code": "short-lived-code",
                    **extra,
                }
            ),
            follow_redirects=False,
        )

    def bind(self, user_id=None, **extra):
        return self.client.post(
            "/api/v1/auth/identities",
            json={
                "user_id": user_id or self.user["id"],
                "provider_id": "example",
                "subject": "provider-subject",
                **extra,
            },
        )


@pytest.fixture
def oidc_env(settings, tmp_path, signing_key):
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "example",
                        "label": "Example Identity",
                        "issuer": ISSUER,
                        "client_id": "boxen-client",
                    }
                ]
            }
        )
    )
    settings.oauth_providers_file = config_path
    setup_token = initialize(settings)
    app = create_app(settings)
    with TestClient(app) as client:
        client.event_hooks["response"].append(check_response)
        client.event_hooks["request"].append(
            lambda request: (
                request.headers.setdefault("Idempotency-Key", str(uuid.uuid4()))
                if request.method not in {"GET", "HEAD"}
                else None
            )
        )
        client.headers["Origin"] = settings.origin
        response = client.post(
            "/api/v1/setup/owner",
            headers={"X-Boxen-Setup-Token": setup_token},
            json={
                "username": "owner",
                "display_name": "Core Owner",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201, response.text
        owner = response.json()["user"]
        csrf = response.json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        user_response = client.post(
            "/api/v1/users",
            json={
                "username": "linked-user",
                "display_name": "Linked User",
                "role": "viewer",
                "password": PASSWORD,
            },
        )
        assert user_response.status_code == 201, user_response.text
        env = Environment(
            client,
            app.state.oauth,
            owner,
            user_response.json(),
            csrf,
            signing_key,
            {
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token",
                "jwks_uri": ISSUER + "/keys",
                "response_types_supported": ["code"],
                "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                "code_challenge_methods_supported": ["S256"],
            },
            [],
            {},
            [],
        )
        env.service.transport = httpx.MockTransport(env.transport)
        yield env


def test_provider_views_do_not_expose_secret_and_disabled_provider_is_hidden(oidc_env):
    env = oidc_env
    assert env.client.get("/api/v1/auth/providers").json() == {
        "items": [{"id": "example", "label": "Example Identity"}]
    }
    status = env.client.get("/api/v1/auth/provider-status")
    assert status.json()["items"][0] == {
        "id": "example",
        "label": "Example Identity",
        "issuer": ISSUER,
        "client_id": "boxen-client",
        "configured": True,
        "redirect_uri": "http://testserver/api/v1/auth/oidc/example/callback",
    }
    env.service.providers["example"] = env.service.providers["example"].model_copy(update={"enabled": False})
    assert env.client.get("/api/v1/auth/providers").json() == {"items": []}
    assert env.client.post("/api/v1/auth/oidc/example/start", json={}).status_code == 404


def test_start_requires_same_origin_and_empty_json(oidc_env):
    env = oidc_env
    for headers, body, expected in [
        ({"Origin": "https://attacker.test"}, {}, 403),
        ({}, {"return_to": "https://attacker.test"}, 422),
    ]:
        response = env.client.post("/api/v1/auth/oidc/example/start", json=body, headers=headers)
        assert response.status_code == expected
    assert not env.requests


def test_code_flow_pkce_cookie_sessions_audit_and_transient_tokens(oidc_env):
    env = oidc_env
    assert env.bind().status_code == 201
    query = env.start()
    assert query["scope"] == ["openid"]
    assert query["max_age"] == ["0"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://testserver/api/v1/auth/oidc/example/callback"]
    cookie = next(cookie for cookie in env.client.cookies.jar if cookie.name == "boxen_oidc")
    assert cookie.path == "/api/v1/auth/oidc/" and cookie._rest["SameSite"] == "lax"
    assert "HttpOnly" in cookie._rest
    with env.service.database.transaction() as repo:
        pending = repo.one("oidc_transactions", state_hash=digest(query["state"][0]))
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(pending["code_verifier"].encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert query["code_challenge"] == [challenge]
        assert query["state"][0] not in json.dumps(pending)
    response = env.callback(query, iss=ISSUER)
    assert response.status_code == 302 and response.headers["location"] == "/"
    SUCCESSES.add("completeOIDCSignIn")
    assert (
        "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    )
    assert "boxen_oidc" not in env.client.cookies
    session = env.client.get("/api/v1/session")
    assert session.json()["user"]["id"] == env.user["id"]
    token_request = next(request for request in env.requests if request.url.path == "/token")
    form = parse_qs(token_request.content.decode())
    assert form["code_verifier"] == [pending["code_verifier"]]
    with env.service.database.transaction() as repo:
        assert not repo.find("oidc_transactions")
        sessions = repo.find("sessions", user_id=env.user["id"])
        assert len(sessions) == 1 and sessions[0]["method"] == "oidc"
        assert repo.find("audit_log", action="auth.login")[-1]["actor_user_id"] == env.user["id"]
        contents = " ".join(
            json.dumps(repo.find(name))
            for name in ("sessions", "external_identities", "app_settings", "audit_log")
        )
        assert "never-persist" not in contents


@pytest.mark.parametrize(
    "patch",
    [
        {"iss": "https://other.test"},
        {"aud": "other-client"},
        {"azp": "other-client"},
        {"aud": ["boxen-client", "other-client"]},
        {"nonce": "incorrect"},
        {"nonce": 1},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"iat": int(time.time()) - 3600},
        {"auth_time": int(time.time()) - 3600},
        {"auth_time": int(time.time()) + 3600},
        {"auth_time": True},
        {"auth_time": "123"},
        {"auth_time": float("nan")},
        {"exp": float("inf")},
        {"iat": float("inf")},
        {"sub": ""},
        {"sub": "\u00e9"},
    ],
)
def test_invalid_claims_fail_once_with_generic_redirect(oidc_env, patch):
    env = oidc_env
    assert env.bind().status_code == 201
    env.claims_patch = patch
    query = env.start()
    response = env.callback(query)
    assert response.status_code == 302 and response.headers["location"] == "/login?oauth_error=failed"
    with env.service.database.transaction() as repo:
        assert not repo.find("sessions", user_id=env.user["id"])
        assert not repo.find("oidc_transactions")
        event = repo.find("audit_log", action="auth.login_failed")[-1]
        assert event["actor_user_id"] is None and event["target_public_id"] == "redacted"
    env.claims_patch = {}
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"


@pytest.mark.parametrize("missing", ["nonce", "auth_time", "exp", "iat", "iss", "aud", "sub"])
def test_missing_required_claims_rejected(oidc_env, missing):
    env = oidc_env
    env.bind()
    env.missing_claims = [missing]
    assert env.callback(env.start()).headers["location"] == "/login?oauth_error=failed"


def test_valid_multiple_audiences_requires_correct_authorized_party(oidc_env):
    env = oidc_env
    env.bind()
    env.claims_patch = {"aud": ["boxen-client", "api"], "azp": "boxen-client"}
    assert env.callback(env.start()).headers["location"] == "/"


def test_state_is_browser_bound_and_one_use(oidc_env):
    env = oidc_env
    env.bind()
    query = env.start()
    browser = env.client.cookies["boxen_oidc"]
    env.client.cookies.delete("boxen_oidc")
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"
    assert not any(request.url.path == "/token" for request in env.requests)
    env.client.cookies.set("boxen_oidc", browser, domain="testserver.local", path="/api/v1/auth/oidc/")
    assert env.callback(query).headers["location"] == "/"
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"
    assert sum(request.url.path == "/token" for request in env.requests) == 1


def test_expired_state_provider_mixup_and_duplicate_code_rejected(oidc_env):
    env = oidc_env
    env.bind()
    query = env.start()
    with env.service.database.transaction(write=True) as repo:
        repo.update("oidc_transactions", {"expires_at": after(-1)}, state_hash=digest(query["state"][0]))
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"
    query = env.start()
    assert env.callback(query, iss="https://other.test").headers["location"] == "/login?oauth_error=failed"
    query = env.start()
    url = (
        "/api/v1/auth/oidc/example/callback?"
        + urlencode({"state": query["state"][0], "code": "a"})
        + "&code=b"
    )
    assert env.client.get(url, follow_redirects=False).headers["location"] == "/login?oauth_error=failed"
    assert not any(request.url.path == "/token" for request in env.requests)


def test_unbound_email_and_roles_do_not_create_or_escalate_accounts(oidc_env):
    env = oidc_env
    env.claims_patch = {
        "email": "owner@example.test",
        "preferred_username": "owner",
        "role": "owner",
        "groups": ["admin"],
    }
    assert env.callback(env.start()).headers["location"] == "/login?oauth_error=failed"
    assert env.bind().status_code == 201
    assert env.callback(env.start()).headers["location"] == "/"
    session = env.client.get("/api/v1/session").json()
    assert session["user"]["role"] == "viewer"
    with env.service.database.transaction() as repo:
        assert len(repo.find("users")) == 2


@pytest.mark.parametrize("disabled", ["user", "provider"])
def test_disabled_user_or_provider_cannot_complete(oidc_env, disabled):
    env = oidc_env
    env.bind()
    query = env.start()
    if disabled == "provider":
        env.service.providers["example"] = env.service.providers["example"].model_copy(
            update={"enabled": False}
        )
    else:
        with env.service.database.transaction(write=True) as repo:
            repo.update("users", {"status": "disabled"}, id=env.user["id"])
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"


def test_admin_link_acl_core_protection_uniqueness_and_unlink_revocation(oidc_env):
    env = oidc_env
    assert env.bind(env.owner["id"]).status_code == 403
    original_csrf = env.client.headers.pop("X-CSRF-Token")
    assert env.bind().status_code == 403
    env.client.headers["X-CSRF-Token"] = original_csrf
    linked = env.bind()
    assert linked.status_code == 201
    assert env.bind().status_code == 409
    listed = env.client.get("/api/v1/auth/identities", params={"user_id": env.user["id"]})
    assert listed.json() == {"items": [linked.json()]}
    with env.service.database.transaction(write=True) as repo:
        user = repo.one("users", id=env.user["id"])
        for method in ("password", "oidc"):
            env.service.identity.start_session(repo, user, "session-for-unlink", method=method)
    deleted = env.client.delete("/api/v1/auth/identities/" + linked.json()["id"])
    assert deleted.status_code == 204
    with env.service.database.transaction() as repo:
        assert not repo.find("external_identities")
        assert all(session["revoked_at"] for session in repo.find("sessions", user_id=env.user["id"]))
    env.client.post("/api/v1/auth/login", json={"username": "linked-user", "password": PASSWORD})
    assert env.client.get("/api/v1/auth/provider-status").status_code == 403
    assert env.client.get("/api/v1/auth/identities").status_code == 403


def test_sensitive_link_requires_recent_owner(oidc_env):
    env = oidc_env
    with env.service.database.transaction(write=True) as repo:
        for session in repo.find("sessions", user_id=env.owner["id"]):
            repo.update("sessions", {"created_at": after(-901)}, token_hash=session["token_hash"])
    assert env.bind().json()["code"] == "auth.reauthentication_required"


@pytest.mark.parametrize(
    "change",
    [
        {"issuer": "https://other.test"},
        {"token_endpoint": "http://identity.example.test/token"},
        {"authorization_endpoint": "https://user:pass@identity.example.test/authorize"},
        {"jwks_uri": {"unexpected": "type"}},
        {"response_types_supported": ["token"]},
        {"id_token_signing_alg_values_supported": ["HS256"]},
        {"code_challenge_methods_supported": ["plain"]},
        {"response_types_supported": "code"},
    ],
)
def test_untrusted_discovery_rejected(oidc_env, change):
    env = oidc_env
    env.metadata.update(change)
    assert env.client.post("/api/v1/auth/oidc/example/start", json={}).status_code == 503


def test_redirects_and_oversized_provider_responses_rejected(oidc_env):
    env = oidc_env
    env.status = 302
    assert env.client.post("/api/v1/auth/oidc/example/start", json={}).status_code == 503
    env.service.transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1))
    )
    assert env.client.post("/api/v1/auth/oidc/example/start", json={}).status_code == 503


@pytest.mark.parametrize(
    "keys",
    [
        [],
        [None],
        [{"kty": "oct", "k": "aGVsbG8", "kid": "signing"}],
        [{"kty": "RSA", "kid": "signing", "key_ops": None}],
    ],
)
def test_invalid_signing_keys_fail_generically(oidc_env, keys):
    env = oidc_env
    env.bind()
    env.jwks_override = {"keys": keys}
    assert env.callback(env.start()).headers["location"] == "/login?oauth_error=failed"


def test_unsigned_token_rejected(oidc_env):
    env = oidc_env
    env.bind()
    env.token_override = jwt.encode({"sub": "provider-subject"}, "", algorithm="none")
    assert env.callback(env.start()).headers["location"] == "/login?oauth_error=failed"


def test_es256_public_key_verification(oidc_env):
    env = oidc_env
    env.bind()
    query = env.start()
    key = ec.generate_private_key(ec.SECP256R1())
    env.jwks_override = {
        "keys": [
            {
                **json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key())),
                "kid": "signing",
                "alg": "ES256",
            }
        ]
    }
    env.token_override = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "provider-subject",
            "aud": "boxen-client",
            "nonce": env.nonce,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "auth_time": int(time.time()),
        },
        key,
        algorithm="ES256",
        headers={"kid": "signing"},
    )
    assert env.callback(query).headers["location"] == "/"


def test_configuration_secrets_permissions_and_duplicate_clients(tmp_path):
    path = tmp_path / "providers.json"
    secret = tmp_path / "client.secret"
    secret.write_text("test-client-secret\n")
    secret.chmod(0o600)
    provider = {
        "id": "example",
        "label": "Example",
        "issuer": ISSUER,
        "client_id": "boxen-client",
        "client_secret_file": "client.secret",
    }
    path.write_text(json.dumps({"providers": [provider]}))
    assert load_providers(path)["example"].client_secret_file == str(secret)
    secret.chmod(0o644)
    with pytest.raises(RuntimeError):
        load_providers(path)
    secret.chmod(0o600)
    path.write_text(json.dumps({"providers": [provider, {**provider, "id": "duplicate"}]}))
    with pytest.raises(RuntimeError):
        load_providers(path)
    path.write_text(json.dumps({"providers": [{**provider, "issuer": "http://identity.example.test"}]}))
    with pytest.raises(RuntimeError):
        load_providers(path)


def test_confidential_client_secret_is_sent_only_to_token_endpoint(oidc_env, tmp_path):
    env = oidc_env
    secret = tmp_path / "client.secret"
    secret.write_text("private-secret-value")
    secret.chmod(0o600)
    env.service.providers["example"] = env.service.providers["example"].model_copy(
        update={"client_secret_file": str(secret)}
    )
    env.bind()
    assert env.callback(env.start()).headers["location"] == "/"
    for request in env.requests:
        if request.url.path == "/token":
            assert request.headers["authorization"].startswith("Basic ")
        else:
            assert "authorization" not in request.headers


def test_start_is_rate_limited_before_provider_network(oidc_env):
    env = oidc_env
    with env.service.database.transaction(write=True) as repo:
        key = env.service.identity.rate_key("example", "testclient", "oidc-start")
        repo.set_setting(key, {"count": 20, "until": after(900)})
    response = env.client.post("/api/v1/auth/oidc/example/start", json={})
    assert response.status_code == 429
    assert not env.requests


def test_invalid_callbacks_have_bounded_audit_growth(oidc_env):
    env = oidc_env
    for _ in range(65):
        response = env.client.get(
            "/api/v1/auth/oidc/example/callback?state=invalid&code=invalid", follow_redirects=False
        )
        assert response.headers["location"] == "/login?oauth_error=failed"
    with env.service.database.transaction() as repo:
        assert len(repo.find("audit_log", action="auth.login_failed")) == 60
        assert not repo.find("oidc_transactions")
    assert not env.requests


@pytest.mark.parametrize("algorithm", ["RS256", "HS256"])
def test_forged_signatures_and_symmetric_algorithm_confusion_rejected(oidc_env, algorithm):
    env = oidc_env
    env.bind()
    query = env.start()
    claims = {
        "iss": ISSUER,
        "sub": "provider-subject",
        "aud": "boxen-client",
        "nonce": env.nonce,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "auth_time": int(time.time()),
    }
    key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if algorithm == "RS256"
        else "attacker-secret-256-bits-long-value"
    )
    env.token_override = jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "signing"})
    assert env.callback(query).headers["location"] == "/login?oauth_error=failed"
    with env.service.database.transaction() as repo:
        assert not repo.find("sessions", user_id=env.user["id"])


def test_provider_requests_never_hold_sqlite_writer_lock(oidc_env):
    env = oidc_env

    def other_writer_during_provider_request(request):
        with env.service.database.transaction(write=True) as repo:
            repo.set_setting("test-independent-writer", request.url.path)
        return env.transport(request)

    env.service.transport = httpx.MockTransport(other_writer_during_provider_request)
    env.bind()
    assert env.callback(env.start()).headers["location"] == "/"


def test_provider_declined_signin_consumes_state_without_token_exchange(oidc_env):
    env = oidc_env
    query = env.start()
    assert env.callback(query, error="access_denied").headers["location"] == "/login?oauth_error=failed"
    with env.service.database.transaction() as repo:
        assert not repo.find("oidc_transactions")
    assert not any(request.url.path == "/token" for request in env.requests)


def test_confidential_client_post_authentication(oidc_env, tmp_path):
    env = oidc_env
    secret = tmp_path / "client.secret"
    secret.write_text("private-post-secret")
    secret.chmod(0o600)
    env.service.providers["example"] = env.service.providers["example"].model_copy(
        update={"client_secret_file": str(secret)}
    )
    env.metadata["token_endpoint_auth_methods_supported"] = ["client_secret_post"]
    env.bind()
    assert env.callback(env.start()).headers["location"] == "/"
    request = next(request for request in env.requests if request.url.path == "/token")
    assert parse_qs(request.content.decode())["client_secret"] == ["private-post-secret"]
    assert "authorization" not in request.headers
