"""Remote transport contract, using synthetic profiles/images and mock HTTP only."""

import base64
import io
import json
import os
import ssl
import traceback
from pathlib import Path

import certifi
import httpx
import pytest
from boxen.analysis.infrastructure.runtime import command
from boxen.analysis.infrastructure.vision import GENERATION_SCHEMA, LocalVision
from boxen.platform.config import Settings
from boxen.shared.errors import DomainError
from PIL import Image
from test_ai_operations import analysis_fixture
from test_vision_adapter import compact_output
from test_vision_adapter import installed as installed
from test_workflows import create_box


@pytest.fixture
def remote(installed, tmp_path):
    settings, local_root = installed
    root = tmp_path / "remote-metadata" / settings.ai_profile
    root.mkdir(parents=True)
    (root / "manifest.json").write_bytes((local_root / "manifest.json").read_bytes())
    configured = Settings.model_validate(
        {
            **settings.model_dump(),
            "ai_mode": "remote",
            "ai_base_url": "https://inference.example.test/team/",
            "ai_models_dir": root.parent,
        }
    )
    return configured, root


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "synthetic.webp"
    Image.new("RGB", (1200, 600), "white").save(path, "WEBP")
    return path


def mock_http(monkeypatch, handle):
    original = httpx.Client
    options = []

    def client(**kwargs):
        options.append(kwargs)
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["verify"] is not False
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    return options


def response(settings, *, reason="stop", content=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": reason,
                    "message": {
                        "content": json.dumps(compact_output(settings)) if content is None else content
                    },
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 180},
        },
    )


def test_settings_defaults_empty_env_and_models_directory(monkeypatch, tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    assert settings.ai_mode == "local"
    assert settings.ai_profile is None
    assert settings.ai_models_dir is None
    assert settings.models_dir == (tmp_path / "data/models").resolve()
    assert settings.ai_api_key_file is None and settings.ai_ca_file is None
    assert settings.ai_allow_insecure_http is False
    for field in ("AI_PROFILE", "AI_MODELS_DIR", "AI_API_KEY_FILE", "AI_CA_FILE"):
        monkeypatch.setenv("BOXEN_" + field, "")
    assert Settings.load().ai_profile is None
    assert Settings.load().ai_models_dir is None
    monkeypatch.setenv("BOXEN_AI_MODELS_DIR", str(tmp_path / "independent-models"))
    assert Settings.load().models_dir == tmp_path / "independent-models"
    monkeypatch.setenv("BOXEN_AI_MODE", "remote")
    monkeypatch.setenv("BOXEN_AI_BASE_URL", "http://inference.example.test/base/")
    with pytest.raises(ValueError, match="HTTPS"):
        Settings.load()
    monkeypatch.setenv("BOXEN_AI_ALLOW_INSECURE_HTTP", "true")
    assert Settings.load().ai_base_url == "http://inference.example.test/base"


@pytest.mark.parametrize("field", ["ai_api_key_file", "ai_ca_file"])
def test_credentials_and_ca_are_remote_only_settings(field, monkeypatch, tmp_path):
    path = tmp_path / "not-read-during-configuration"
    with pytest.raises(ValueError, match="require BOXEN_AI_MODE=remote"):
        Settings(**{field: path})
    monkeypatch.setenv("BOXEN_AI_MODE", "local")
    monkeypatch.setenv("BOXEN_AI_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("BOXEN_" + field.upper(), str(path))
    with pytest.raises(ValueError, match="require BOXEN_AI_MODE=remote"):
        Settings.load()
    monkeypatch.setenv("BOXEN_AI_MODE", "remote")
    monkeypatch.setenv("BOXEN_AI_BASE_URL", "https://inference.example.test")
    assert getattr(Settings.load(), field) == path


@pytest.mark.parametrize(
    "url", ["http://localhost:8080/", "http://127.0.0.1:8080/", "http://[::1]:8080/", "http://boxen-ai:8080/"]
)
def test_local_urls_remain_supported_and_normalize(url):
    assert Settings(ai_base_url=url).ai_base_url == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    ["https://localhost", "http://10.0.0.2:8080", "https://inference.example.test", "http://localhost/base"],
)
def test_local_mode_cannot_opt_into_remote_by_changing_url_or_http_flag(url):
    with pytest.raises(ValueError):
        Settings(ai_base_url=url, ai_allow_insecure_http=True)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://inference.example.test",
        "https://user:password@example.test",
        "https://@example.test",
        "https://example.test?query",
        "https://example.test?",
        "https://example.test#fragment",
        "https://example.test#",
        "https://*.example.test",
        "https://0.0.0.0",
        "https://[::]",
        "https://[0:0::0]",
        "https:///nohost",
        "https://example.test:0",
        "https://example.test:65536",
        "https://example.test:-1",
        "https://example.test:notaport",
        "https://example.test:",
        "https://[broken",
        "https://example.test\n",
        "https://example.test\\elsewhere",
        "https://example.test/with space",
    ],
)
def test_remote_rejects_invalid_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        Settings(ai_mode="remote", ai_base_url=url)


@pytest.mark.parametrize(
    "url",
    ["https://example.test/", "https://example.test/base/v2/", "https://127.0.0.1:8443/", "https://[::1]/"],
)
def test_remote_https_root_or_base_path(url):
    assert Settings(ai_mode="remote", ai_base_url=url).ai_base_url == url.rstrip("/")


def test_metadata_only_remote_profile_and_local_launcher_refusal(remote):
    settings, root = remote
    assert [p.name for p in root.iterdir()] == ["manifest.json"]
    vision = LocalVision(settings)
    assert vision.profile
    assert "Remote (operator-reported)" in vision.profile["display_name"]
    assert vision.artifact_verification == "operator_reported_not_locally_verified"
    with pytest.raises(ValueError, match="Remote"):
        command(settings)
    local = settings.model_copy(update={"ai_mode": "local", "ai_base_url": "http://localhost:8080"})
    assert LocalVision(local).error == "ai.profile_invalid"
    with pytest.raises(ValueError, match="checksum"):
        command(local)


@pytest.mark.parametrize("artifact", ["model", "projector", "runtime"])
@pytest.mark.parametrize("digest", [None, "", "unknown", "a" * 63, "g" * 64, 123])
def test_remote_requires_declared_sha256_for_every_artifact(remote, artifact, digest):
    settings, root = remote
    manifest = json.loads((root / "manifest.json").read_text())
    manifest[artifact]["sha256"] = digest
    (root / "manifest.json").write_text(json.dumps(manifest))
    assert LocalVision(settings).error == "ai.profile_invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_sha256", "0" * 64),
        ("output_schema_sha256", "0" * 64),
        ("profile_version", 2),
        ("prompt_version", "old"),
        ("max_image_edge", 4096),
        ("max_output_tokens", 8193),
        ("initial_output_tokens", 8192),
        ("worker_slots", 2),
        ("seed", "1"),
        ("license_files", []),
        ("display_name", None),
        ("max_output_tokens", 1024.5),
    ],
)
def test_remote_keeps_profile_metadata_and_resource_validation(remote, field, value):
    settings, root = remote
    manifest = json.loads((root / "manifest.json").read_text())
    manifest[field] = value
    (root / "manifest.json").write_text(json.dumps(manifest))
    assert LocalVision(settings).error == "ai.profile_invalid"


def test_remote_readiness_auth_strict_vision_and_default_tls(remote, photo, tmp_path, monkeypatch):
    settings, _ = remote
    key = tmp_path / "key"
    key.write_text("synthetic-secret-token")
    settings.ai_api_key_file = key
    for field in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        monkeypatch.setenv(field, "invalid-environment-override")
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer synthetic-secret-token"
        assert request.url.host == "inference.example.test"
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})
        payload = json.loads(request.content)
        assert payload["model"] == "fixture-model"
        assert "chat_template_kwargs" not in payload
        assert payload["response_format"]["json_schema"] == {
            "name": "boxen_inventory",
            "strict": True,
            "schema": GENERATION_SCHEMA,
        }
        image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        with Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as image:
            assert image.size == (512, 256) and image.format == "JPEG" and not image.getexif()
        return response(settings)

    options = mock_http(monkeypatch, handle)
    vision = LocalVision(settings)
    ready = vision.readiness()
    assert ready["status"] == "ready"
    assert "operator-reported" in ready["message"] and "not locally verified" in ready["message"]
    assert len(vision.analyze(photo)["observations"]) == 1
    assert seen == [("GET", "/team/v1/models"), ("POST", "/team/v1/chat/completions")]
    assert all(option["verify"] is True for option in options)


def test_configured_ca_still_enforces_certificates_and_hostname(remote, monkeypatch):
    settings, _ = remote
    settings.ai_ca_file = Path(certifi.where())
    options = mock_http(
        monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "fixture-model"}]})
    )
    assert LocalVision(settings).readiness()["status"] == "ready"
    context = options[0]["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.get_ca_certs()


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
@pytest.mark.parametrize("length", [1, 4096])
def test_secret_accepts_one_terminal_line_ending(remote, photo, tmp_path, monkeypatch, ending, length):
    settings, _ = remote
    key = tmp_path / "token-with-line-ending"
    token = b"x" * length
    key.write_bytes(token + ending)
    settings.ai_api_key_file = key

    def handle(request):
        assert request.headers["Authorization"] == "Bearer " + token.decode("ascii")
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})
        return response(settings)

    mock_http(monkeypatch, handle)
    vision = LocalVision(settings)
    assert vision.readiness()["status"] == "ready"
    assert len(vision.analyze(photo)["observations"]) == 1


@pytest.mark.parametrize(
    "kind",
    [
        "missing_key",
        "missing_ca",
        "invalid_ca",
        "directory_key",
        "fifo_key",
        "empty_key",
        "multiple_lf",
        "multiple_crlf",
        "embedded_lf",
        "bare_cr",
        "only_lf",
        "only_crlf",
        "header",
        "oversized",
        "oversized_crlf",
        "unicode",
        "space",
    ],
)
def test_bad_secret_or_ca_fails_closed_without_leaking(remote, photo, tmp_path, monkeypatch, caplog, kind):
    settings, _ = remote
    path = tmp_path / "sensitive-file-name"
    if kind.endswith("ca"):
        settings.ai_ca_file = path
        if kind == "invalid_ca":
            path.write_text("synthetic-private-secret")
    else:
        settings.ai_api_key_file = path
        if kind == "directory_key":
            path.mkdir()
        elif kind == "fifo_key":
            os.mkfifo(path)
        elif kind != "missing_key":
            path.write_text(
                {
                    "empty_key": "",
                    "multiple_lf": "synthetic-private-secret\n\n",
                    "multiple_crlf": "synthetic-private-secret\r\n\r\n",
                    "embedded_lf": "synthetic-private-secret\nsecond-line",
                    "bare_cr": "synthetic-private-secret\r",
                    "only_lf": "\n",
                    "only_crlf": "\r\n",
                    "header": "synthetic-private-secret\r\nX-Injected: yes",
                    "oversized": "x" * 4097,
                    "oversized_crlf": "x" * 4097 + "\r\n",
                    "unicode": "synthetic-private-secreté",
                    "space": "synthetic-private-secret token",
                }[kind]
            )
    called = []
    mock_http(monkeypatch, lambda request: called.append(request))
    vision = LocalVision(settings)
    assert vision.readiness()["code"] == "ai.transport_invalid"
    with pytest.raises(DomainError) as caught:
        vision.analyze(photo)
    rendered = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert caught.value.code == "ai.transport_invalid"
    assert "synthetic-private-secret" not in rendered and "sensitive-file-name" not in rendered
    assert not called


@pytest.mark.parametrize(
    "body", [{}, {"data": []}, {"data": [{"id": "other-model"}]}, {"data": "wrong"}, {"data": [None]}]
)
def test_readiness_requires_configured_model(remote, monkeypatch, body):
    settings, _ = remote
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert LocalVision(settings).readiness()["status"] == "unavailable"


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 500])
def test_redirects_and_errors_never_follow_or_reveal_provider_body(
    remote, photo, monkeypatch, caplog, status
):
    settings, _ = remote
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status, text="synthetic-secret-provider-error", headers={"Location": "https://elsewhere.invalid"}
        )

    mock_http(monkeypatch, handle)
    vision = LocalVision(settings)
    assert vision.readiness()["status"] == "unavailable"
    with pytest.raises(DomainError) as caught:
        vision.analyze(photo)
    assert caught.value.code == "ai.runtime_unavailable"
    assert len(calls) == 2 and all(call.url.host == "inference.example.test" for call in calls)
    assert (
        "synthetic-secret-provider-error"
        not in "".join(traceback.format_exception(caught.value)) + caplog.text
    )


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'{"choices": [], "choices": []}',
        b'{"choices": [null]}',
        b'{"choices": [{"finish_reason":"secret-refusal"}]}',
        b"x" * (513 * 1024),
    ],
)
def test_malformed_and_oversized_remote_envelopes_are_sanitized(remote, photo, monkeypatch, body):
    settings, _ = remote
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=body))
    vision = LocalVision(settings)
    with pytest.raises(DomainError) as caught:
        vision.analyze(photo)
    assert caught.value.code == "ai.output_invalid"
    assert "secret-refusal" not in json.dumps(vision.last_metrics)


@pytest.mark.parametrize(
    "content", ["not-json", '{"items":[]}', '{"secret-provider-value":1}', "x" * (129 * 1024)]
)
def test_remote_compact_schema_and_size_failures_do_not_leak(remote, photo, monkeypatch, content):
    settings, _ = remote
    mock_http(monkeypatch, lambda request: response(settings, content=content))
    with pytest.raises(DomainError) as caught:
        LocalVision(settings).analyze(photo)
    assert caught.value.code == "ai.output_invalid"
    assert "secret-provider-value" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_remote_length_retry_is_bounded_and_partial_results_never_saved(remote, photo, monkeypatch, finish):
    settings, _ = remote
    vision = LocalVision(settings)
    vision.profile["initial_output_tokens"] = 512
    budgets = []

    def handle(request):
        budgets.append(json.loads(request.content)["max_tokens"])
        return response(settings, reason="length" if len(budgets) == 1 else finish)

    mock_http(monkeypatch, handle)
    if finish == "length":
        with pytest.raises(DomainError) as caught:
            vision.analyze(photo)
        assert caught.value.code == "ai.output_truncated"
    else:
        assert len(vision.analyze(photo)["observations"]) == 1
    assert budgets == [512, 1024]
    assert vision.last_metrics["input_tokens"] == 200
    assert vision.last_metrics["output_tokens"] == 360


@pytest.mark.parametrize("mode,offline", [("local", True), ("remote", False)])
def test_system_status_offline_contract(client, mode, offline):
    services = client.app.state.services
    services.operations.settings.ai_mode = mode
    # Remote mode loses the offline guarantee even when its URL is private.
    services.operations.settings.ai_base_url = "http://127.0.0.1:8080"
    result = client.get("/api/v1/system")
    assert result.status_code == 200, result.text
    assert result.json()["runtime_offline"] is offline


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_job_review_and_verified_or_declared_provenance(client, installed, remote, photo, monkeypatch, mode):
    settings, _ = remote if mode == "remote" else installed
    services = client.app.state.services
    vision = LocalVision(settings)
    services.analysis.vision = vision
    box = create_box(client).json()
    image = client.post(
        f"/api/v1/boxes/{box['code']}/images",
        files={"file": ("synthetic.webp", photo.read_bytes(), "image/webp")},
    ).json()
    mock_http(monkeypatch, lambda request: response(settings))
    requested = client.post(f"/api/v1/images/{image['id']}/analyses", json={})
    assert requested.status_code == 202, requested.text
    job = services.analysis.claim("mock-remote-worker")
    services.analysis.execute(job)
    status = client.get("/api/v1/jobs/" + job["id"]).json()
    assert status["state"] == "succeeded"
    assert client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"] == []
    run = client.get("/api/v1/analysis-runs/" + status["run_id"]).json()
    assert run["model"]["sha256"] == vision.profile["model"]["sha256"]
    assert run["model"]["projector_sha256"] == vision.profile["projector"]["sha256"]
    with services.database.transaction() as repo:
        provenance = repo.setting("run-provenance:" + run["id"])
    assert provenance["ai_mode"] == mode
    assert provenance["artifact_verification"] == (
        "operator_reported_not_locally_verified" if mode == "remote" else "local_checksums_verified"
    )
    assert provenance["inference_input_sha256"] == vision.last_input_sha256
    assert provenance["runtime_sha256"] == vision.profile["runtime"]["sha256"]
    assert provenance["inference_requests"] == vision.last_metrics["requests"]
    observation = run["observations"][0]
    assert observation["decision"] == "pending"
    accepted = client.post(
        f"/api/v1/observations/{observation['id']}/accept",
        json={"mode": "create", "item": {"name": "Reviewed wrench", "quantity": "1", "unit": "piece"}},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["item"]["provenance"] == "ai"
    assert len(client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"]) == 1


@pytest.mark.parametrize(
    "kind,code,attempts",
    [
        ("invalid", "ai.output_invalid", 2),
        ("truncated", "ai.output_truncated", 1),
        ("unavailable", "ai.runtime_unavailable", 3),
    ],
)
def test_remote_failed_jobs_keep_retry_limits_and_no_partial_observations(
    client, remote, monkeypatch, kind, code, attempts
):
    settings, _ = remote
    services, _, box, _, requested = analysis_fixture(client)
    services.analysis.vision = LocalVision(settings)

    def handle(request):
        if kind == "unavailable":
            return httpx.Response(503, text="synthetic-private-provider-error")
        return response(settings, reason="length" if kind == "truncated" else "stop", content="{}")

    mock_http(monkeypatch, handle)
    for attempt in range(1, attempts + 1):
        services.analysis.execute(services.analysis.claim("mock-remote-worker"))
        status = client.get("/api/v1/jobs/" + requested["id"]).json()
        assert status["state"] == ("queued" if attempt < attempts else "failed")
        assert status["attempt_count"] == attempt and status["error"]["code"] == code
        with services.database.transaction(write=True) as repo:
            run = repo.find("ai_runs", job_id=requested["id"])[-1]
            assert run["raw_output_json"] is None
            assert "synthetic-private-provider-error" not in run["error_summary"]
            assert (
                repo.setting("run-provenance:" + run["id"])["artifact_verification"]
                == "operator_reported_not_locally_verified"
            )
            repo.set_setting("retry:" + requested["id"], "")
    assert services.analysis.claim("mock-remote-worker") is None
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == []
    assert client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"] == []


@pytest.mark.parametrize(
    "error,code", [(httpx.ConnectError, "ai.runtime_unavailable"), (httpx.ReadTimeout, "ai.timeout")]
)
def test_remote_connection_errors_are_sanitized_and_never_fall_back(remote, photo, monkeypatch, error, code):
    settings, _ = remote
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.scheme == "https"
        assert "Authorization" not in request.headers
        raise error("synthetic-private-provider-error", request=request)

    mock_http(monkeypatch, handle)
    vision = LocalVision(settings)
    assert vision.readiness()["status"] == "unavailable"
    with pytest.raises(DomainError) as caught:
        vision.analyze(photo)
    assert caught.value.code == code
    assert "synthetic-private-provider-error" not in "".join(traceback.format_exception(caught.value))
    assert len(calls) == 2
