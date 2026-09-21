import copy
import io

import pytest
from boxen.analysis.infrastructure.vision import LocalVision
from boxen.operations.infrastructure.backup import Backups
from boxen.platform.contracts import validate_payload
from boxen.shared.errors import DomainError
from boxen.shared.values import after
from PIL import Image
from test_workflows import create_box


class FakeVision(LocalVision):
    """Deterministic adapter fixture. No production fake-runtime flag exists."""

    def __init__(self, settings):
        super().__init__(settings)
        self.profile = {
            "profile_id": "test-profile",
            "model": {"id": "fixture-model", "sha256": "1" * 64},
            "projector": {"sha256": "2" * 64},
            "runtime": {"id": "fixture", "version": "1", "sha256": "3" * 64},
            "temperature": 0,
            "seed": 0,
            "max_output_tokens": 1024,
        }
        self.output = {
            "schema_version": "1.0",
            "scene_quality": "good",
            "summary": "A hand tool",
            "warnings": [],
            "observations": [
                {
                    "name": "Adjustable wrench",
                    "quantity": 1,
                    "unit": "piece",
                    "confidence": 0.8,
                    "bounding_box": None,
                    "attributes": {
                        "color": "silver",
                        "material": None,
                        "brand": None,
                        "model": None,
                        "visible_text": None,
                    },
                    "evidence": "A visible metal wrench",
                }
            ],
        }

    def analyze(self, path):
        return copy.deepcopy(self.output)


def analysis_fixture(client):
    app = client.app.state.services
    fake = FakeVision(app.settings)
    app.analysis.vision = fake
    box = create_box(client).json()
    image = io.BytesIO()
    Image.new("RGB", (120, 100), "gray").save(image, "JPEG")
    response = client.post(
        f"/api/v1/boxes/{box['code']}/images", files={"file": ("test.jpg", image.getvalue(), "image/jpeg")}
    )
    assert response.status_code == 201, response.text
    photo = response.json()
    requested = client.post(f"/api/v1/images/{photo['id']}/analyses", json={})
    assert requested.status_code == 202, requested.text
    return app, fake, box, photo, requested.json()


def test_analysis_review_is_atomic_and_does_not_auto_inventory(client):
    app, fake, box, photo, requested = analysis_fixture(client)
    job = app.analysis.claim("test-worker")
    assert job["id"] == requested["id"]
    assert app.analysis.claim("another-worker") is None
    app.analysis.execute(job)
    complete = client.get("/api/v1/jobs/" + job["id"])
    assert complete.json()["state"] == "succeeded", complete.text
    assert (
        client.get(
            "/api/v1/jobs/" + job["id"], headers={"If-None-Match": complete.headers["etag"]}
        ).status_code
        == 304
    )
    assert not client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"]
    run = client.get("/api/v1/analysis-runs/" + complete.json()["run_id"])
    validate_payload(run.json(), {"$ref": "#/components/schemas/AnalysisRunView"})
    observations = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    assert len(observations) == 1
    accepted = client.post(
        "/api/v1/observations/" + observations[0]["id"] + "/accept",
        json={"mode": "create", "item": {"name": "Wrench", "quantity": "1", "unit": "piece"}},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["item"]["provenance"] == "ai"
    assert (
        client.post("/api/v1/observations/" + observations[0]["id"] + "/reject", json={}).status_code == 409
    )
    assert "Wrench" in client.get("/api/v1/search?q=wrench").text
    app.analysis.execute(job)
    with app.database.transaction() as repo:
        assert len(repo.find("ai_runs", job_id=job["id"])) == 1


def test_invalid_ai_output_has_no_observations_and_retries(client):
    app, fake, box, photo, requested = analysis_fixture(client)
    fake.output["observations"][0]["quantity"] = -10
    job = app.analysis.claim("worker")
    app.analysis.execute(job)
    result = client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["state"] == "queued"
    assert result["error"]["code"] == "ai.output_invalid"
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == []
    with app.database.transaction() as repo:
        run = repo.find("ai_runs", job_id=job["id"])[0]
        assert run["raw_output_json"] is None


def test_exhausted_token_budget_does_not_repeat_entire_job(client):
    app, fake, box, photo, requested = analysis_fixture(client)

    def exhausted(_path):
        fake.last_metrics = {
            "input_tokens": 200,
            "output_tokens": 6144,
            "requests": [{"max_output_tokens": 2048}, {"max_output_tokens": 4096}],
        }
        raise DomainError("ai.output_truncated", "Use closer photos of smaller groups.")

    fake.analyze = exhausted
    app.analysis.execute(app.analysis.claim("worker"))
    result = client.get("/api/v1/jobs/" + requested["id"]).json()
    assert result["state"] == "failed" and result["attempt_count"] == 1
    assert result["error"]["code"] == "ai.output_truncated"
    assert app.analysis.claim("worker") is None
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == []
    run = client.get("/api/v1/analysis-runs/" + result["run_id"]).json()
    assert run["metrics"]["output_tokens"] == 6144


def test_latest_analysis_survives_navigation_and_empty_results(client):
    app, fake, box, photo, requested = analysis_fixture(client)
    assert client.get("/api/v1/images/" + photo["id"]).json()["latest_analysis"]["id"] == requested["id"]
    current = client.get(f"/api/v1/boxes/{box['code']}").json()
    assert current["images"][0]["latest_analysis"]["state"] == "queued"
    duplicate = client.post(f"/api/v1/images/{photo['id']}/analyses", json={})
    assert duplicate.status_code == 409
    fake.output["observations"] = []
    app.analysis.execute(app.analysis.claim("worker"))
    photos = client.get(f"/api/v1/boxes/{box['code']}/images").json()["items"]
    assert photos[0]["latest_analysis"]["state"] == "succeeded"
    assert photos[0]["latest_analysis"]["id"] == requested["id"]
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == []


def test_two_photo_views_link_to_one_item_without_inflating_quantity(client):
    app, fake, box, photo, first = analysis_fixture(client)
    app.analysis.execute(app.analysis.claim("worker"))
    image = io.BytesIO()
    Image.new("RGB", (100, 120), "green").save(image, "JPEG")
    second_photo = client.post(
        f"/api/v1/boxes/{box['code']}/images",
        files={"file": ("close-up.jpg", image.getvalue(), "image/jpeg")},
    ).json()
    client.post(f"/api/v1/images/{second_photo['id']}/analyses", json={})
    app.analysis.execute(app.analysis.claim("worker"))
    observations = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    assert len(observations) == 2
    assert len({o["image_id"] for o in observations}) == 2
    accepted = client.post(
        f"/api/v1/observations/{observations[0]['id']}/accept",
        json={"mode": "create", "item": {"name": "Wrench", "quantity": "1", "unit": "piece"}},
    ).json()
    item = accepted["item"]
    current = client.get("/api/v1/items/" + item["id"])
    linked = client.post(
        f"/api/v1/observations/{observations[1]['id']}/accept",
        json={"mode": "merge", "item_id": item["id"], "item_etag": current.headers["etag"]},
    )
    assert linked.status_code == 200, linked.text
    inventory = client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"]
    assert len(inventory) == 1 and inventory[0]["quantity"] == "1"


def test_expired_lease_fences_old_worker_and_archive_cancels(client):
    app, fake, box, photo, requested = analysis_fixture(client)
    first = app.analysis.claim("first")
    with app.database.transaction(write=True) as repo:
        repo.update("analysis_jobs", {"lease_expires_at": after(-60)}, id=first["id"])
    second = app.analysis.claim("second")
    assert second["lease_token"] != first["lease_token"]
    app.analysis.execute(first)
    assert client.get("/api/v1/jobs/" + first["id"]).json()["state"] == "running"
    current = client.get("/api/v1/boxes/" + box["code"])
    archived = client.post(
        "/api/v1/boxes/" + box["code"] + "/archive", headers={"If-Match": current.headers["etag"]}
    )
    assert archived.status_code == 200
    app.analysis.execute(second)
    assert client.get("/api/v1/jobs/" + first["id"]).json()["state"] == "cancelled"


def test_backup_verify_restore_preflight_and_purge(client):
    box = create_box(client)
    code = box.json()["code"]
    app = client.app.state.services
    backup = client.post("/api/v1/backups")
    assert backup.status_code == 202, backup.text
    assert app.operations.run_once()
    status = client.get("/api/v1/backups/" + backup.json()["id"])
    assert status.json()["status"] == "verified", status.text
    with app.database.transaction() as repo:
        row = repo.one("backups", id=backup.json()["id"])
        installation = repo.setting("installation_id")
    path = app.backups.path(row)
    assert app.backups.restore(path, installation)["status"] == "ready"
    with pytest.raises(DomainError, match="Stop the web"):
        app.backups.restore(path, installation, apply=True)
    archived = client.post("/api/v1/boxes/" + code + "/archive", headers={"If-Match": box.headers["etag"]})
    purged = client.post(
        "/api/v1/boxes/" + code + "/purge",
        headers={"If-Match": archived.headers["etag"]},
        json={"confirmation_code": code},
    )
    assert purged.status_code == 204, purged.text
    assert client.get("/api/v1/boxes/" + code).status_code == 404
    with app.database.transaction() as repo:
        assert repo.one("box_code_tombstones", public_code=code)
    # Synthetic backup corruption is detected without changing live data.
    (path / "configuration/public-settings.json").write_text("{}")
    with pytest.raises(DomainError):
        Backups.verify(path)


def test_search_drift_rebuild_and_direct_code_fallback(client):
    box = create_box(client).json()
    app = client.app.state.services
    with app.database.transaction(write=True) as repo:
        repo.execute("DELETE FROM box_search")
    for action in ["verify", "rebuild"]:
        request = client.post("/api/v1/maintenance/search/" + action)
        assert request.status_code == 202, request.text
        assert app.operations.run_once()
        result = client.get("/api/v1/maintenance/" + request.json()["id"]).json()
        assert result["state"] == "succeeded"
        if action == "verify":
            assert result["result"]["mismatches"] == 1
            assert client.get("/api/v1/search?q=cables").status_code == 503
            assert box["code"] in client.get("/api/v1/search?q=" + box["code"]).text
    assert box["code"] in client.get("/api/v1/search?q=cables").text
