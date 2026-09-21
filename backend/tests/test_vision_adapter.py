import base64
import hashlib
import io
import json

import httpx
import pytest
from boxen.analysis.infrastructure.vision import GENERATION_SCHEMA, PROMPT, PROMPT_VERSION, LocalVision
from boxen.shared.errors import DomainError
from PIL import Image
from test_ai_operations import FakeVision


def compact_output(settings):
    output = FakeVision(settings).output
    return {
        **{key: output[key] for key in ("scene_quality", "summary", "warnings")},
        "items": [
            {
                key: value
                for key, value in observation.items()
                if key in {"name", "quantity", "confidence", "evidence"}
            }
            for observation in output["observations"]
        ],
    }


@pytest.fixture
def installed(settings):
    root = settings.data_dir / "models/test-profile"
    root.mkdir(parents=True)
    artifacts = {}
    for name in ["model", "projector", "runtime"]:
        data = ("synthetic " + name).encode()
        (root / name).write_bytes(data)
        artifacts[name] = {
            "id": "fixture-" + name,
            "version": "1",
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    (root / "LICENSE").write_text("Synthetic fixture; no actual model weights.")
    profile = {
        "profile_id": "test-profile",
        "profile_version": 1,
        "display_name": "Fixture profile",
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": "1.0",
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "output_schema_sha256": hashlib.sha256(
            (settings.assets / "ai-inventory-output.schema.json").read_bytes()
        ).hexdigest(),
        "license_files": ["LICENSE"],
        "worker_slots": 1,
        "max_output_tokens": 1024,
        "max_image_edge": 512,
        "temperature": 0,
        "seed": 0,
        **artifacts,
    }
    (root / "manifest.json").write_text(json.dumps(profile))
    return settings.model_copy(update={"ai_profile": "test-profile"}), root


def test_verified_profile_and_local_http_adapter(installed, monkeypatch):
    settings, root = installed
    vision = LocalVision(settings)
    assert vision.profile
    compact = compact_output(settings)
    output = vision.expand(json.dumps(compact).encode())

    def handle(request):
        assert request.url.host == "boxen-ai"
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_schema"
        content = payload["messages"][1]["content"]
        assert payload["response_format"]["json_schema"]["schema"] == GENERATION_SCHEMA
        assert "laid out" in payload["messages"][0]["content"]
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as sent:
            assert sent.format == "JPEG"
            assert sent.size == (512, 256)
            assert not sent.getexif()
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(compact)}}]})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
    )
    assert vision.readiness()["status"] == "ready"
    image = root / "image.webp"
    Image.new("RGB", (1200, 600), "white").save(image, "WEBP")
    assert vision.analyze(image) == output
    (root / "model").write_bytes(b"corrupted")
    assert LocalVision(settings).error == "ai.profile_invalid"


@pytest.mark.parametrize("kind", ["timeout", "unavailable", "invalid", "oversized", "truncated"])
def test_runtime_failures_are_bounded(installed, monkeypatch, kind):
    settings, root = installed
    vision = LocalVision(settings)

    def handle(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if kind == "unavailable":
            return httpx.Response(503)
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * (513 * 1024))
        if kind == "truncated":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": json.dumps(FakeVision(settings).output)},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"choices": []})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
    )
    image = root / "image.webp"
    Image.new("RGB", (20, 20)).save(image, "WEBP")
    with pytest.raises(DomainError) as error:
        vision.analyze(image)
    assert error.value.code in {
        "ai.timeout",
        "ai.runtime_unavailable",
        "ai.output_invalid",
        "ai.output_truncated",
    }


def test_length_retry_increases_budget_and_records_usage(installed, monkeypatch):
    settings, root = installed
    vision = LocalVision(settings)
    vision.profile["initial_output_tokens"] = 512
    budgets = []

    def handle(request):
        budgets.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if len(budgets) == 1 else "stop",
                        "message": {
                            "content": '{"items":['
                            if len(budgets) == 1
                            else json.dumps(compact_output(settings))
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 512 if len(budgets) == 1 else 180},
            },
        )

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    path = root / "photo.png"
    Image.new("RGB", (20, 20)).save(path)
    result = vision.analyze(path)
    assert budgets == [512, 1024]
    assert len(result["observations"]) == 1
    assert result["observations"][0]["bounding_box"] is None
    assert all(v is None for v in result["observations"][0]["attributes"].values())
    assert vision.last_metrics["input_tokens"] == 200
    assert vision.last_metrics["output_tokens"] == 692


def test_truncation_is_bounded_and_never_salvages_partial_inventory(installed, monkeypatch):
    settings, root = installed
    vision = LocalVision(settings)
    vision.profile["initial_output_tokens"] = 512
    budgets = []

    def handle(request):
        budgets.append(json.loads(request.content)["max_tokens"])
        # Even parseable complete JSON must not be accepted when more output was cut off.
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "length", "message": {"content": json.dumps(compact_output(settings))}}
                ]
            },
        )

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    path = root / "photo.png"
    Image.new("RGB", (20, 20)).save(path)
    with pytest.raises(DomainError) as raised:
        vision.analyze(path)
    assert raised.value.code == "ai.output_truncated"
    assert budgets == [512, 1024]


def test_compact_output_stays_strict_and_preserves_uncertain_counts(installed):
    settings, _ = installed
    vision = LocalVision(settings)
    compact = compact_output(settings)
    compact["items"][0]["quantity"] = None
    result = vision.expand(json.dumps(compact).encode())
    assert result["observations"][0]["quantity"] is None
    assert result["observations"][0]["unit"] is None
    compact["items"][0]["invented_brand"] = "unsupported"
    with pytest.raises(DomainError):
        vision.expand(json.dumps(compact).encode())


def test_output_retry_cannot_reset_total_time_budget(installed, monkeypatch):
    from boxen.analysis.infrastructure import vision as adapter

    settings, root = installed
    settings.ai_timeout = 1
    vision = LocalVision(settings)
    vision.profile["initial_output_tokens"] = 512
    clock = [0.0]
    calls = []
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])

    def handle(request):
        calls.append(json.loads(request.content)["max_tokens"])
        clock[0] += 0.75
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        )

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    path = root / "photo.png"
    Image.new("RGB", (20, 20)).save(path)
    with pytest.raises(DomainError) as raised:
        vision.analyze(path)
    assert raised.value.code == "ai.timeout"
    assert calls == [512, 1024]
