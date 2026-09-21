"""Opt-in real inference; no mocked responses, no downloads, disposable inventory.

Provide BOXEN_REAL_AI_PROFILE_ROOT and BOXEN_REAL_AI_COFFEE_IMAGE. The latter is
the CC0 scikit-image coffee.png photograph, visually reviewed in ai-local-cpu.md.
An already running, loopback-only llama.cpp server is required.
"""

import json
import os
from pathlib import Path

import pytest
from boxen.analysis.infrastructure.vision import PREPROCESSING_VERSION, LocalVision
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from boxen.worker.main import tick
from test_anonymous_access import browser, session
from test_workflows import create_box


def real_vision():
    root = Path(os.environ["BOXEN_REAL_AI_PROFILE_ROOT"]).resolve(strict=True)
    settings = Settings(
        env="test",
        origin="http://testserver",
        data_dir=root.parent.parent,
        ai_profile=root.name,
        ai_base_url=os.environ.get("BOXEN_REAL_AI_URL", "http://127.0.0.1:8080"),
    )
    vision = LocalVision(settings)
    assert vision.profile, vision.error
    assert vision.readiness()["status"] == "ready"
    return vision


@pytest.fixture
def anonymous_ai_client(settings):
    settings.anonymous_access = "editor"
    initialize(settings)
    with browser(create_app(settings), settings.origin) as client:
        current = session(client).json()
        assert current["anonymous"] is True
        assert current["user"]["role"] == "editor"
        assert "box.edit" in current["capabilities"]
        assert client.get("/api/v1/setup/status").json() == {"setup_required": True}
        with client.app.state.services.database.transaction() as repo:
            assert repo.find("users", role="owner") == []
        yield client


@pytest.mark.skipif(not os.environ.get("BOXEN_REAL_AI_PROFILE_ROOT"), reason="real local model opt-in")
def test_real_photo_recognition_then_reviewed_inventory(anonymous_ai_client):
    client = anonymous_ai_client
    root = Path(os.environ["BOXEN_REAL_AI_PROFILE_ROOT"]).resolve(strict=True)
    image = Path(os.environ["BOXEN_REAL_AI_COFFEE_IMAGE"]).resolve(strict=True)
    settings = Settings(
        env="test",
        origin="http://testserver",
        data_dir=root.parent.parent,
        ai_profile=root.name,
        ai_base_url=os.environ.get("BOXEN_REAL_AI_URL", "http://127.0.0.1:8080"),
    )
    vision = LocalVision(settings)
    assert vision.profile, vision.error
    assert vision.readiness()["status"] == "ready"
    app = client.app.state.services
    app.vision = app.analysis.vision = vision
    # Only the model files are shared. The client fixture creates a new database
    # and media store under pytest's temporary directory, never the user's data.
    assert app.settings.data_dir != settings.data_dir
    box = create_box(client, "Real vision review test").json()
    uploaded = client.post(
        f"/api/v1/boxes/{box['code']}/images",
        files={"file": ("coffee.png", image.read_bytes(), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    requested = client.post(f"/api/v1/images/{uploaded.json()['id']}/analyses", json={})
    assert requested.status_code == 202, requested.text
    assert tick(app, "real-model-verification", schedule=False)
    job = client.get("/api/v1/jobs/" + requested.json()["id"]).json()
    assert job["state"] == "succeeded", job
    observations = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    assert observations and all(item["decision"] == "pending" for item in observations)
    assert client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"] == []
    cups = [
        item
        for item in observations
        if any(word in item["proposed_name"].casefold() for word in ("cup", "mug"))
    ]
    assert cups, observations
    # Explicit review action, using the cup visibly present in the test photo.
    accepted = client.post(
        f"/api/v1/observations/{cups[0]['id']}/accept",
        json={"mode": "create", "item": {"name": "Coffee cup", "quantity": "1", "unit": "piece"}},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["item"]["provenance"] == "ai"
    inventory = client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"]
    assert len(inventory) == 1 and inventory[0]["name"] == "Coffee cup"
    assert box["code"] in client.get("/api/v1/search", params={"q": "Coffee cup"}).text
    assert client.get("/api/v1/setup/status").json() == {"setup_required": True}
    with app.database.transaction() as repo:
        run = repo.one("ai_runs", id=job["run_id"])
        provenance = repo.setting("run-provenance:" + job["run_id"])
    assert provenance["inference_input_sha256"] == vision.last_input_sha256
    assert provenance["preprocessing_version"] == PREPROCESSING_VERSION
    assert run["model_sha256"] == vision.profile["model"]["sha256"]
    print(
        json.dumps(
            {
                "real_model_output": json.loads(run["raw_output_json"]),
                "access": {"anonymous": True, "role": "editor", "setup_required": True},
                "duration_ms": run["duration_ms"],
                "provenance": provenance,
                "review": "explicit accept request; zero items before review; one searchable AI-provenance cup after",
            },
            indent=2,
        )
    )


@pytest.mark.skipif(not os.environ.get("BOXEN_REAL_AI_IMAGE"), reason="real user-photo regression opt-in")
def test_real_uploaded_photo_finishes_without_partial_inventory(anonymous_ai_client):
    """Read the selected photo locally; all jobs/media/results are disposable.

    Do not print image bytes, filenames, item names or private model content.
    """
    client = anonymous_ai_client
    vision = real_vision()
    app = client.app.state.services
    assert app.settings.data_dir != vision.settings.data_dir
    app.vision = app.analysis.vision = vision
    image = Path(os.environ["BOXEN_REAL_AI_IMAGE"]).resolve(strict=True)
    box = create_box(client, "Photo collection regression").json()
    uploaded = client.post(
        f"/api/v1/boxes/{box['code']}/images",
        files={"file": ("contents.webp", image.read_bytes(), "image/webp")},
    )
    assert uploaded.status_code == 201, uploaded.text
    requested = client.post(f"/api/v1/images/{uploaded.json()['id']}/analyses", json={})
    assert requested.status_code == 202, requested.text
    assert tick(app, "real-collection-verification", schedule=False)
    job = client.get("/api/v1/jobs/" + requested.json()["id"]).json()
    assert job["state"] == "succeeded", job
    observations = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    assert observations and all(o["decision"] == "pending" for o in observations)
    assert client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"] == []
    with app.database.transaction() as repo:
        run = repo.one("ai_runs", id=job["run_id"])
    assert run["input_tokens"] > 0 and run["output_tokens"] > 0
    assert len(vision.last_metrics["requests"]) in (1, 2)
    assert vision.last_metrics["requests"][-1]["finish_reason"] == "stop"
    print(
        json.dumps(
            {
                "test": "real user-photo regression",
                "suggestion_count": len(observations),
                "duration_ms": run["duration_ms"],
                "metrics": vision.last_metrics,
                "confirmed_inventory_count": 0,
            }
        )
    )
