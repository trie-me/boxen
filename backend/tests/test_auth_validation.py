import json

import pytest
from boxen.api.app import create_app
from boxen.identity.domain import validate_user
from boxen.operations.infrastructure.database import initialize
from boxen.platform.contracts import validate_payload
from boxen.shared.errors import DomainError
from conftest import check_response
from fastapi.testclient import TestClient

OWNER = {
    "username": "owner",
    "display_name": "Local Owner",
    "password": "long-unique-test-passphrase",
}
SETUP_HEADER = "X-Boxen-Setup-Token"


@pytest.fixture
def setup_client(settings):
    token = initialize(settings)
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        client.headers["Origin"] = settings.origin
        client.event_hooks["response"].append(check_response)
        yield client, token


def field_errors(response, code="request.validation", status=422):
    assert response.status_code == status, response.text
    problem = response.json()
    assert problem["code"] == code
    validate_payload(problem, {"$ref": "#/components/schemas/ProblemDetails"})
    assert problem["errors"]
    assert all(set(field) == {"path", "code", "message"} for field in problem["errors"])
    assert response.headers["cache-control"] == "no-store"
    return {field["path"]: field for field in problem["errors"]}


@pytest.mark.parametrize(
    "token,message",
    [
        ("short-private-setup-token", "Use at least 43 characters."),
        ("s" * 42, "Use at least 43 characters."),
        ("s" * 257, "Use no more than 256 characters."),
    ],
)
def test_setup_token_length_is_actionable_without_echo(setup_client, token, message):
    client, actual_token = setup_client
    response = client.post("/api/v1/setup/owner", headers={SETUP_HEADER: token}, json=OWNER)
    fields = field_errors(response)
    assert fields["/headers/X-Boxen-Setup-Token"]["message"] == message
    assert token not in response.text
    assert actual_token not in response.text
    assert OWNER["password"] not in response.text
    assert client.get("/api/v1/setup/status").json() == {"setup_required": True}


def test_missing_setup_token_has_a_field(setup_client):
    client, token = setup_client
    response = client.post("/api/v1/setup/owner", json=OWNER)
    fields = field_errors(response, "request.parameter_required")
    assert fields == {
        "/headers/X-Boxen-Setup-Token": {
            "path": "/headers/X-Boxen-Setup-Token",
            "code": "value.required",
            "message": "This field is required.",
        }
    }
    assert token not in response.text
    assert OWNER["password"] not in response.text


@pytest.mark.parametrize("route", ["/setup/owner", "/auth/login"])
def test_missing_body_fields_point_to_the_missing_properties(setup_client, route):
    client, token = setup_client
    response = client.post("/api/v1" + route, headers={SETUP_HEADER: token}, json={})
    fields = field_errors(response)
    expected = {"/username", "/password"}
    if route == "/setup/owner":
        expected.add("/display_name")
    assert set(fields) == expected
    assert len(response.json()["errors"]) == len(expected)
    assert all(field["message"] == "This field is required." for field in fields.values())


@pytest.mark.parametrize(
    "field,value,code,message",
    [
        ("username", "x", "request.validation", "Use at least 3 characters."),
        ("username", "invalid/user", "user.username_invalid", "3–64 letters"),
        ("display_name", " \t\n ", "value.invalid", "1–120 characters without control characters"),
        ("display_name", "x" * 121, "request.validation", "Use no more than 120 characters."),
        ("password", "shortsecret", "request.validation", "Use at least 12 characters."),
        ("password", "密" * 11, "request.validation", "Use at least 12 characters."),
        ("password", "p" * 1025, "request.validation", "Use no more than 1024 characters."),
        ("password", "🙂" * 257, "user.password_invalid", "no more than 1024 bytes"),
        ("password", "passwordpassword", "user.password_common", "Choose a less common password."),
        ("password", {"private-secret-key": "private-secret-value"}, "request.validation", "Use text."),
    ],
)
def test_setup_body_validation_is_actionable_and_safe(setup_client, field, value, code, message):
    client, token = setup_client
    response = client.post("/api/v1/setup/owner", headers={SETUP_HEADER: token}, json={**OWNER, field: value})
    fields = field_errors(response, code)
    assert set(fields) == {"/" + field}
    assert message in fields["/" + field]["message"]
    assert token not in response.text
    assert OWNER["password"] not in response.text
    assert "private-secret" not in response.text
    if isinstance(value, str) and len(value) > 3 and not value.isspace():
        assert value not in json.dumps(response.json(), ensure_ascii=False)
    assert client.get("/api/v1/setup/status").json() == {"setup_required": True}


@pytest.mark.parametrize(
    "body,path,message",
    [
        ({"username": "owner", "password": ""}, "/password", "Use at least 1 character."),
        ({"username": "owner", "password": None}, "/password", "Use text."),
        ({"username": "owner", "password": "secret" * 200}, "/password", "Use no more than 1024 characters."),
        ({"username": ["private-name"], "password": "secret"}, "/username", "Use text."),
    ],
)
def test_login_schema_errors_are_attached_without_secret_values(setup_client, body, path, message):
    client, _ = setup_client
    response = client.post("/api/v1/auth/login", json=body)
    assert field_errors(response)[path]["message"] == message
    assert "secret" not in response.text
    assert "private-name" not in response.text


@pytest.mark.parametrize(
    "url,path,code,message",
    [
        ("/boxes?limit=101", "/query/limit", "request.validation", "Use a value no greater than 100."),
        ("/boxes?limit=0", "/query/limit", "request.validation", "Use a value of at least 1."),
        ("/boxes?limit=private-secret", "/query/limit", "request.parameter_invalid", "Use a whole number."),
        ("/users/not-a-uuid", "/path/user_id", "request.validation", "Use a valid UUID."),
    ],
)
def test_parameter_errors_include_their_location(client, url, path, code, message):
    response = client.get("/api/v1" + url)
    assert field_errors(response, code)[path]["message"] == message
    assert "private-secret" not in response.text


def test_header_validation_and_missing_precondition_keep_existing_status(client):
    response = client.post("/api/v1/boxes", headers={"Idempotency-Key": "short-secret"}, json={"name": "Box"})
    assert field_errors(response)["/headers/Idempotency-Key"]["message"] == "Use at least 16 characters."
    assert "short-secret" not in response.text
    response = client.patch("/api/v1/session/profile", json={"display_name": "Updated Owner"})
    assert "/headers/If-Match" in field_errors(response, "resource.precondition_required", 428)


def test_json_pointers_escape_nested_property_names_and_include_array_indexes():
    schema = {
        "type": "object",
        "properties": {
            "section/~": {
                "type": "array",
                "items": {"type": "object", "required": ["user/name~", "password"]},
            }
        },
    }
    with pytest.raises(DomainError) as caught:
        validate_payload({"section/~": [{}]}, schema, prefix="/body")
    assert {field["path"] for field in caught.value.errors} == {
        "/body/section~1~0/0/user~1name~0",
        "/body/section~1~0/0/password",
    }
    with pytest.raises(DomainError) as caught:
        validate_payload(None, {"type": "object"})
    assert caught.value.errors == [{"path": "/", "code": "value.invalid", "message": "Use an object."}]


def test_missing_field_errors_are_unique_and_remain_bounded():
    with pytest.raises(DomainError) as caught:
        validate_payload({}, {"type": "object", "required": [f"field{index}" for index in range(30)]})
    assert len(caught.value.errors) == 20
    assert len({field["path"] for field in caught.value.errors}) == 20


def test_extra_secret_property_names_and_values_are_not_echoed():
    with pytest.raises(DomainError) as caught:
        validate_payload(
            {**OWNER, "private-secret-key": "private-secret-value"},
            {"$ref": "#/components/schemas/OwnerSetupRequest"},
        )
    assert caught.value.errors == [
        {"path": "/", "code": "value.invalid", "message": "Remove unsupported fields."}
    ]
    assert "private-secret" not in json.dumps(caught.value.errors)


@pytest.mark.parametrize("password", ["  Correct-密-🙂-passphrase  ", "🙂" * 256])
def test_valid_setup_session_logout_and_login_preserve_password_bytes(setup_client, settings, password):
    client, token = setup_client
    body = {**OWNER, "password": password}
    created = client.post("/api/v1/setup/owner", headers={SETUP_HEADER: token}, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["user"]["role"] == "owner"
    assert created.json()["anonymous"] is False
    assert client.get("/api/v1/session").json() == created.json()
    assert client.get("/api/v1/setup/status").json() == {"setup_required": False}
    assert not (settings.data_dir / "secrets/setup-token").exists()
    csrf = created.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/session").status_code == 401
    logged_in = client.post("/api/v1/auth/login", json={"username": OWNER["username"], "password": password})
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["user"] == created.json()["user"]
    assert client.get("/api/v1/session").json() == logged_in.json()
    assert logged_in.json()["csrf_token"] != csrf


def test_login_keeps_credential_failures_generic_and_rate_limited(setup_client):
    client, _ = setup_client
    # Login still accepts a one-character password syntactically; the creation
    # strength policy must not replace credential checking or rate limiting.
    for _ in range(5):
        response = client.post("/api/v1/auth/login", json={"username": "invalid/user", "password": "x"})
        assert response.status_code == 401
        assert response.json()["code"] == "auth.invalid_credentials"
        assert "errors" not in response.json()
    response = client.post("/api/v1/auth/login", json={"username": "invalid/user", "password": "x"})
    assert response.status_code == 429
    assert response.json()["code"] == "auth.rate_limited"
    assert int(response.headers["retry-after"]) > 0


def test_setup_token_verification_and_rate_limiting_are_unchanged(setup_client):
    client, token = setup_client
    invalid_token = "invalid-private-setup-token-" + "x" * 43
    for _ in range(5):
        response = client.post("/api/v1/setup/owner", headers={SETUP_HEADER: invalid_token}, json=OWNER)
        assert response.status_code == 403
        assert response.json()["code"] == "setup.token_invalid"
        assert invalid_token not in response.text
        assert token not in response.text
    response = client.post("/api/v1/setup/owner", headers={SETUP_HEADER: token}, json=OWNER)
    assert response.status_code == 429
    assert response.json()["code"] == "auth.rate_limited"
    assert int(response.headers["retry-after"]) > 0
    assert client.get("/api/v1/setup/status").json() == {"setup_required": True}


def test_domain_password_validation_retains_a_field_for_direct_callers():
    with pytest.raises(DomainError) as caught:
        validate_user({"password": "secret"})
    assert caught.value.code == "user.password_invalid"
    assert caught.value.errors == [
        {
            "path": "/password",
            "code": "user.password_invalid",
            "message": "Use at least 12 characters and no more than 1024 bytes.",
        }
    ]
