import re
import uuid
from pathlib import Path

import pytest
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from boxen.platform.contracts import api_contract, resolve, validate_payload
from fastapi.testclient import TestClient

SUCCESSES = set()


def check_response(response):
    """Validate every tested success response against the unchanged public contract."""
    if response.status_code >= 300:
        return
    path = response.request.url.path.removeprefix("/api/v1")
    for template, operations in api_contract()["paths"].items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path):
            operation = operations.get(response.request.method.lower())
            if not operation:
                continue
            schema = (
                resolve(operation["responses"][str(response.status_code)])
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if schema:
                response.read()
                validate_payload(response.json(), schema)
            SUCCESSES.add(operation["operationId"])
            return


def pytest_terminal_summary(terminalreporter):
    expected = {
        op["operationId"]
        for operations in api_contract()["paths"].values()
        for method, op in operations.items()
        if method in {"get", "post", "patch", "put", "delete"}
    }
    terminalreporter.write_line(f"OpenAPI success coverage: {len(SUCCESSES)}/{len(expected)} operations")
    if expected - SUCCESSES:
        terminalreporter.write_line("Not exercised successfully: " + ", ".join(sorted(expected - SUCCESSES)))


@pytest.fixture
def settings(tmp_path: Path):
    return Settings(
        env="test",
        origin="http://testserver",
        anonymous_access="off",
        data_dir=tmp_path / "data",
        disk_reserve_bytes=0,
        disk_reserve_percent=0,
    )


@pytest.fixture
def client(settings):
    token = initialize(settings)
    with TestClient(create_app(settings)) as client:
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
            headers={"X-Boxen-Setup-Token": token},
            json={
                "username": "owner",
                "display_name": "Local Owner",
                "password": "long-unique-test-passphrase",
            },
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client
