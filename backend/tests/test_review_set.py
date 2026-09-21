import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from boxen.shared.values import etag
from PIL import Image
from test_ai_operations import analysis_fixture
from test_anonymous_access import browser, session
from test_workflows import create_box


@pytest.fixture
def review_box(client):
    app, fake, box, photo, _ = analysis_fixture(client)
    template = fake.output["observations"][0]
    fake.output["observations"] = [{**template, "name": f"Tool {i}"} for i in range(4)]
    app.analysis.execute(app.analysis.claim("review-test"))
    observations = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    assert len(observations) == 4
    return box, observations


def accept(observation, **item):
    return {
        "observation_id": observation["id"],
        "decision": {"mode": "create", "item": {"name": "Reviewed tool", **item}},
    }


def link(observation, item, **patch):
    return {
        "observation_id": observation["id"],
        "decision": {
            "mode": "merge",
            "item_id": item.json()["id"],
            "item_etag": item.headers["etag"],
            **({"item_patch": patch} if patch else {}),
        },
    }


def review(client, box, body, **kwargs):
    return client.post(f"/api/v1/boxes/{box['code']}/observations/review", json=body, **kwargs)


def snapshot(client):
    """Include audits, idempotency and search to detect partially committed side effects."""
    with client.app.state.services.database.transaction() as repo:
        return {
            **{
                table: repo.find(table)
                for table in (
                    "inventory_items",
                    "item_observations",
                    "audit_log",
                    "idempotency_records",
                    "search_projection_state",
                )
            },
            "search": repo.rows("SELECT * FROM box_search ORDER BY rowid"),
        }


def test_success_mixed_preserves_evidence_and_manual_provenance(client, review_box):
    box, observations = review_box
    code = box["code"]
    existing = client.post(f"/api/v1/boxes/{code}/items", json={"name": "Existing tool", "quantity": "7"})
    response = review(
        client,
        box,
        {
            "accept": [
                accept(observations[0], name="Edited bolts", quantity="2.125", unit="kg"),
                link(observations[1], existing),
            ],
            "reject": [observations[2]["id"]],
            "add": [{"name": "Manual spanner", "quantity": None, "notes_markdown": "**Added** by hand"}],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [r["observation"]["id"] for r in result["accepted"]] == [o["id"] for o in observations[:2]]
    created, linked = result["accepted"]
    assert created["item"]["name"] == "Edited bolts"
    assert created["item"]["quantity"] == "2.125" and created["item"]["unit"] == "kg"
    assert created["item"]["provenance"] == "ai"
    assert linked["item"]["id"] == existing.json()["id"]
    assert linked["item"]["quantity"] == "7" and linked["item"]["provenance"] == "mixed"
    for original, accepted in zip(observations, result["accepted"]):
        evidence = accepted["observation"]
        assert evidence["decision"] == "accepted" and evidence["accepted_item_id"] == accepted["item"]["id"]
        for field in ("image_id", "run_id", "proposed_name", "proposed_quantity", "attributes"):
            assert evidence[field] == original[field]
    assert result["rejected"][0]["id"] == observations[2]["id"]
    assert result["rejected"][0]["decision"] == "rejected"
    assert result["rejected"][0]["accepted_item_id"] is None
    assert result["added"][0]["provenance"] == "manual" and result["added"][0]["quantity"] is None
    assert result["added"][0]["notes"]["source"] == "**Added** by hand"
    assert client.get(f"/api/v1/boxes/{code}/observations").json()["items"] == [observations[3]]
    assert len(client.get(f"/api/v1/boxes/{code}/items").json()["items"]) == 3
    assert code in client.get("/api/v1/search", params={"q": "spanner"}).text
    assert code in client.get("/api/v1/search", params={"q": "bolts"}).text


def test_removed_all_rejects_the_explicit_set(client, review_box):
    box, observations = review_box
    body = {"accept": [], "reject": [o["id"] for o in reversed(observations)], "add": []}
    response = review(client, box, body)
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == response.json()["added"] == []
    assert [o["id"] for o in response.json()["rejected"]] == body["reject"]
    assert all(o["decision"] == "rejected" for o in response.json()["rejected"])
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == []
    assert client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"] == []


def test_manual_only_allows_explicit_identical_items(client):
    box = create_box(client).json()
    item = {"name": "Same label", "quantity": "0.001", "unit": "kg"}
    response = review(client, box, {"accept": [], "reject": [], "add": [item, item]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted"] == result["rejected"] == []
    assert len({i["id"] for i in result["added"]}) == 2
    assert all(i["provenance"] == "manual" and i["quantity"] == "0.001" for i in result["added"])


@pytest.mark.parametrize("patches", [False, True])
def test_multiple_links_validate_original_etag_and_return_final_item(client, review_box, patches):
    box, observations = review_box
    existing = client.post(f"/api/v1/boxes/{box['code']}/items", json={"name": "One wrench", "quantity": "3"})
    entries = [
        link(observations[0], existing, **({"name": "Renamed wrench"} if patches else {})),
        link(observations[1], existing, **({"notes_markdown": "Second view"} if patches else {})),
    ]
    body = {"accept": entries, "reject": [], "add": []}
    response = review(client, box, body)
    assert response.status_code == 200, response.text
    current = client.get("/api/v1/items/" + existing.json()["id"]).json()
    assert current["quantity"] == "3" and current["provenance"] == "mixed"
    assert current["version"] == (4 if patches else 2)
    assert all(r["item"] == current for r in response.json()["accepted"])
    assert all(r["observation"]["accepted_item_id"] == current["id"] for r in response.json()["accepted"])
    if patches:
        assert current["name"] == "Renamed wrench" and current["notes"]["source"] == "Second view"
    assert (
        entries[0]["decision"]["item_etag"] == entries[1]["decision"]["item_etag"] == existing.headers["etag"]
    )


def test_new_pending_from_later_photo_is_untouched(client, review_box):
    box, observations = review_box
    body = {"accept": [accept(observations[0])], "reject": [o["id"] for o in observations[1:]], "add": []}
    photo_bytes = io.BytesIO()
    Image.new("RGB", (100, 120), "green").save(photo_bytes, "JPEG")
    photo = client.post(
        f"/api/v1/boxes/{box['code']}/images",
        files={"file": ("later.jpg", photo_bytes.getvalue(), "image/jpeg")},
    )
    assert photo.status_code == 201, photo.text
    job = client.post(f"/api/v1/images/{photo.json()['id']}/analyses", json={})
    assert job.status_code == 202, job.text
    analysis = client.app.state.services.analysis
    analysis.execute(analysis.claim("later-photo"))
    before = client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"]
    later = [o for o in before if o["image_id"] == photo.json()["id"]]
    assert len(later) == 4
    response = review(client, box, body)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/boxes/{box['code']}/observations").json()["items"] == later


def test_late_domain_failure_rolls_back_items_decisions_search_audit_and_key(client, review_box):
    box, observations = review_box
    existing = client.post(f"/api/v1/boxes/{box['code']}/items", json={"name": "Original", "quantity": "2"})
    body = {
        "accept": [accept(observations[0]), link(observations[1], existing, name="Changed")],
        "reject": [observations[2]["id"]],
        "add": [{"name": "Valid manual item"}, {"name": "   "}],
    }
    before = snapshot(client)
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    response = review(client, box, body, headers=headers)
    assert response.status_code == 422 and response.json()["code"] == "value.invalid", response.text
    assert snapshot(client) == before
    body["add"][-1]["name"] = "Fixed manual item"
    retried = review(client, box, body, headers=headers)
    assert retried.status_code == 200, retried.text
    assert len(retried.json()["accepted"]) == 2 and len(retried.json()["added"]) == 2


@pytest.mark.parametrize("location", ["accept", "reject", "across"])
def test_duplicate_observation_ids_roll_back(client, review_box, location):
    box, observations = review_box
    body = {"accept": [accept(observations[0])], "reject": [], "add": [{"name": "Do not create"}]}
    if location == "accept":
        body["accept"].append(accept(observations[0], name="Different decision for same ID"))
    elif location == "reject":
        body["reject"] = [observations[1]["id"], observations[1]["id"]]
    else:
        body["reject"] = [observations[0]["id"]]
    before = snapshot(client)
    response = review(client, box, body)
    assert response.status_code == 422, response.text
    assert snapshot(client) == before


@pytest.mark.parametrize("decision", ["accept", "reject", "supersede"])
def test_stale_observation_rolls_back(client, review_box, decision):
    box, observations = review_box
    body = {"accept": [accept(observations[0])], "reject": [observations[1]["id"]], "add": [{"name": "New"}]}
    if decision == "supersede":
        photo = client.get("/api/v1/images/" + observations[1]["image_id"])
        response = client.delete(
            "/api/v1/images/" + photo.json()["id"], headers={"If-Match": photo.headers["etag"]}
        )
        assert response.status_code == 204, response.text
    else:
        response = client.post(
            f"/api/v1/observations/{observations[1]['id']}/{decision}",
            json=accept(observations[1])["decision"] if decision == "accept" else {},
        )
        assert response.status_code == 200, response.text
    before = snapshot(client)
    response = review(client, box, body)
    assert response.status_code == 409 and response.json()["code"] == "observation.already_decided"
    assert snapshot(client) == before


@pytest.mark.parametrize("kind", ["accept", "reject", "merge"])
def test_crossbox_reference_rolls_back(client, review_box, kind):
    box, observations = review_box
    app, _, other_box, _, _ = analysis_fixture(client)
    app.analysis.execute(app.analysis.claim("other-box"))
    other_observation = client.get(f"/api/v1/boxes/{other_box['code']}/observations").json()["items"][0]
    body = {"accept": [accept(observations[0])], "reject": [], "add": [{"name": "New"}]}
    if kind == "accept":
        body["accept"].append(accept(other_observation))
    elif kind == "reject":
        body["reject"].append(other_observation["id"])
    else:
        item = client.post(f"/api/v1/boxes/{other_box['code']}/items", json={"name": "Foreign item"})
        body["accept"].append(link(observations[1], item))
    before = snapshot(client)
    response = review(client, box, body)
    assert response.status_code == 409, response.text
    assert snapshot(client) == before


@pytest.mark.parametrize("kind", ["observation", "item"])
def test_missing_reference_rolls_back(client, review_box, kind):
    box, observations = review_box
    body = {"accept": [accept(observations[0])], "reject": [], "add": [{"name": "New"}]}
    if kind == "observation":
        body["reject"].append(str(uuid.uuid4()))
    else:
        body["accept"].append(
            {
                "observation_id": observations[1]["id"],
                "decision": {
                    "mode": "merge",
                    "item_id": str(uuid.uuid4()),
                    "item_etag": '"missing"',
                },
            }
        )
    before = snapshot(client)
    response = review(client, box, body)
    assert response.status_code == 404, response.text
    assert snapshot(client) == before


@pytest.mark.parametrize("invalidity", ["stale", "second_stale", "future", "removed", "remove_patch"])
def test_merge_conflicts_roll_back_entire_review(client, review_box, invalidity):
    box, observations = review_box
    item = client.post(f"/api/v1/boxes/{box['code']}/items", json={"name": "Existing", "quantity": "5"})
    entries = [accept(observations[0]), link(observations[1], item), link(observations[2], item)]
    if invalidity in {"stale", "removed"}:
        changed = client.patch(
            "/api/v1/items/" + item.json()["id"],
            headers={"If-Match": item.headers["etag"]},
            json={"name": "Externally edited"} if invalidity == "stale" else {"lifecycle": "removed"},
        )
        assert changed.status_code == 200, changed.text
    elif invalidity == "second_stale":
        entries[2]["decision"]["item_etag"] = '"stale"'
    elif invalidity == "future":
        # A client must not guess the version after an earlier acceptance changes provenance.
        entries[2]["decision"]["item_etag"] = etag("item", item.json()["id"], 2)
    else:
        entries[2]["decision"]["item_patch"] = {"lifecycle": "removed"}
    before = snapshot(client)
    response = review(
        client, box, {"accept": entries, "reject": [observations[3]["id"]], "add": [{"name": "New"}]}
    )
    assert response.status_code == (409 if invalidity in {"removed", "remove_patch"} else 412), response.text
    assert snapshot(client) == before


def test_same_key_replays_and_changed_body_conflicts(client, review_box):
    box, observations = review_box
    body = {
        "accept": [accept(observations[0])],
        "reject": [observations[1]["id"]],
        "add": [{"name": "Manual"}],
    }
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = review(client, box, body, headers=headers)
    assert first.status_code == 200, first.text
    after = snapshot(client)
    repeat = review(client, box, body, headers=headers)
    assert repeat.status_code == 200 and repeat.json() == first.json()
    assert snapshot(client) == after
    body["add"][0]["name"] = "Different"
    changed = review(client, box, body, headers=headers)
    assert changed.status_code == 409 and changed.json()["code"] == "request.idempotency_conflict"
    assert snapshot(client) == after


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_submissions_commit_once(client, review_box, same_key):
    box, observations = review_box
    body = {
        "accept": [accept(observations[0])],
        "reject": [observations[1]["id"]],
        "add": [{"name": "Manual"}],
    }
    key = str(uuid.uuid4())
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        return review(client, box, body, headers={"Idempotency-Key": key if same_key else str(uuid.uuid4())})

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = [
            future.result(timeout=20) for future in [executor.submit(submit), executor.submit(submit)]
        ]
    assert sorted([first.status_code, second.status_code]) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert first.json() == second.json()
    else:
        conflict = first if first.status_code == 409 else second
        assert conflict.json()["code"] == "observation.already_decided"
    assert len(client.get(f"/api/v1/boxes/{box['code']}/items").json()["items"]) == 2


@pytest.mark.parametrize(
    "anonymous,role", [(False, "editor"), (False, "viewer"), (True, "editor"), (True, "viewer")]
)
def test_editor_and_viewer_permissions(client, settings, review_box, anonymous, role):
    box, observations = review_box
    body = {
        "accept": [accept(observations[0])],
        "reject": [observations[1]["id"]],
        "add": [{"name": "Manual"}],
    }
    if anonymous:
        settings.anonymous_access = role
    else:
        created = client.post(
            "/api/v1/users",
            json={
                "username": "reviewer",
                "display_name": "Reviewer",
                "role": role,
                "password": "reviewer-test-passphrase",
            },
        )
        assert created.status_code == 201, created.text
    with browser(client.app, settings.origin) as other:
        if anonymous:
            session(other)
        else:
            logged_in = other.post(
                "/api/v1/auth/login", json={"username": "reviewer", "password": "reviewer-test-passphrase"}
            )
            assert logged_in.status_code == 200, logged_in.text
            other.headers["X-CSRF-Token"] = logged_in.json()["csrf_token"]
        before = snapshot(client)
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        response = review(other, box, body, headers=headers)
        assert response.status_code == (200 if role == "editor" else 403), response.text
        if role == "viewer":
            assert response.json()["code"] == "auth.forbidden" and snapshot(client) == before
        else:
            after = snapshot(client)
            repeat = review(other, box, body, headers=headers)
            assert repeat.status_code == 200 and repeat.json() == response.json()
            assert snapshot(client) == after
            if anonymous:
                settings.anonymous_access = "viewer"
            else:
                changed = client.patch(
                    "/api/v1/users/" + created.json()["id"],
                    headers={"If-Match": created.headers["etag"]},
                    json={"role": "viewer"},
                )
                assert changed.status_code == 200, changed.text
                # Role changes revoke local sessions; sign in again as the same
                # actor so this also checks authorization before a cached replay.
                logged_in = other.post(
                    "/api/v1/auth/login",
                    json={"username": "reviewer", "password": "reviewer-test-passphrase"},
                )
                assert logged_in.status_code == 200, logged_in.text
                other.headers["X-CSRF-Token"] = logged_in.json()["csrf_token"]
            replay_as_viewer = review(other, box, body, headers=headers)
            assert replay_as_viewer.status_code == 403, replay_as_viewer.text


@pytest.mark.parametrize("violation", ["csrf_missing", "csrf_wrong", "origin", "unauthenticated", "archived"])
def test_csrf_session_and_archive_boundaries(client, review_box, violation):
    box, observations = review_box
    body = {
        "accept": [accept(observations[0])],
        "reject": [observations[1]["id"]],
        "add": [{"name": "Manual"}],
    }
    headers = {}
    if violation == "csrf_missing":
        del client.headers["X-CSRF-Token"]
    elif violation == "csrf_wrong":
        headers["X-CSRF-Token"] = "wrong"
    elif violation == "origin":
        headers["Origin"] = "https://evil.invalid"
    elif violation == "unauthenticated":
        client.cookies.clear()
    else:
        current = client.get(f"/api/v1/boxes/{box['code']}")
        archived = client.post(
            f"/api/v1/boxes/{box['code']}/archive", headers={"If-Match": current.headers["etag"]}
        )
        assert archived.status_code == 200, archived.text
    before = snapshot(client)
    response = review(client, box, body, headers=headers)
    expected = {"unauthenticated": 401, "archived": 409}.get(violation, 403)
    assert response.status_code == expected, response.text
    assert snapshot(client) == before


@pytest.mark.parametrize(
    "invalidity", ["empty", "missing", "extra", "invalid_id", "invalid_item", "array_limit", "total_limit"]
)
def test_request_validation_rolls_back(client, review_box, invalidity):
    box, observations = review_box
    body: dict = {"accept": [], "reject": [], "add": [{"name": "Manual"}]}
    if invalidity == "empty":
        body["add"] = []
    elif invalidity == "missing":
        del body["reject"]
    elif invalidity == "extra":
        body["unknown"] = True
    elif invalidity == "invalid_id":
        body["reject"] = ["not-a-uuid"]
    elif invalidity == "invalid_item":
        body["accept"] = [accept(observations[0], quantity="0")]
    elif invalidity == "array_limit":
        body["add"] *= 501
    else:
        body["add"] *= 500
        body["reject"] = [observations[0]["id"]]
    before = snapshot(client)
    response = review(client, box, body)
    assert response.status_code == 422, response.text
    assert snapshot(client) == before


def test_maximum_combined_action_count_is_allowed(client, review_box):
    box, observations = review_box
    body = {
        "accept": [accept(observations[0])],
        "reject": [observations[1]["id"]],
        "add": [{"name": "Manual"}] * 498,
    }
    response = review(client, box, body)
    assert response.status_code == 200, response.text
    assert len(response.json()["added"]) == 498
    with client.app.state.services.database.transaction() as repo:
        assert len(repo.find("inventory_items")) == 499
