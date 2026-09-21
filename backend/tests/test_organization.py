import uuid

import pytest
from boxen.catalog.domain import BoxCode
from boxen.discovery.infrastructure.search import verify_search
from boxen.shared.values import etag, new_id, now
from test_anonymous_access import browser, session


def box(client, name="Crate", **fields):
    response = client.post("/api/v1/boxes", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response


def collection(client, name="Moving", **fields):
    response = client.post("/api/v1/collections", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response


def box_url(response):
    return "/api/v1/boxes/" + response.json()["code"]


def collection_url(response):
    return "/api/v1/collections/" + response.json()["id"]


def patch(client, url, body, **headers):
    current = client.get(url)
    return client.patch(url, json=body, headers={"If-Match": current.headers["etag"], **headers})


def archive(client, response):
    url = box_url(response)
    current = client.get(url)
    archived = client.post(url + "/archive", headers={"If-Match": current.headers["etag"]})
    assert archived.status_code == 200, archived.text
    return archived


def snapshot(client):
    with client.app.state.services.database.transaction() as repo:
        return {
            **{
                table: repo.find(table)
                for table in (
                    "boxes",
                    "tags",
                    "box_tags",
                    "collections",
                    "collection_boxes",
                    "inventory_items",
                    "audit_log",
                    "idempotency_records",
                )
            },
            "search": repo.rows("SELECT * FROM box_search ORDER BY box_id"),
        }


def codes(response, search=False):
    assert response.status_code == 200, response.text
    return {(row["box"] if search else row)["code"] for row in response.json()["items"]}


def test_empty_collection_crud_and_plaintext(client):
    assert client.get("/api/v1/tags").json() == {"items": []}
    assert client.get("/api/v1/collections").json() == {"items": []}
    created = collection(client, "  Réserves  ", description="**Plain** <b>markup</b>\nSecond line")
    value = created.json()
    assert value["name"] == "Réserves"
    assert value["description"] == "**Plain** <b>markup</b>\nSecond line"
    assert value["version"] == 1
    assert value["box_count"] == value["archived_box_count"] == value["item_count"] == 0
    assert value["boxes"] == value["items"] == []
    assert created.headers["location"] == collection_url(created)
    assert created.headers["etag"] == etag("collection", value["id"], 1)
    read = client.get(collection_url(created))
    assert read.json() == value and read.headers["etag"] == created.headers["etag"]
    changed = patch(client, collection_url(created), {"description": ""})
    assert changed.status_code == 200 and changed.json()["description"] == ""
    assert changed.json()["name"] == value["name"] and changed.json()["version"] == 2
    deleted = client.delete(collection_url(created), headers={"If-Match": changed.headers["etag"]})
    assert deleted.status_code == 204 and not deleted.content
    assert client.get(collection_url(created)).status_code == 404


def test_tag_normalization_reuse_and_explicit_clear(client):
    first = box(client, tags=["  Cafe\u0301 ", "CAFÉ", "Straße", " STRASSE "])
    assert [t["name"] for t in first.json()["tags"]] == ["Café", "Straße"]
    assert first.json()["collections"] == []
    second = box(client, tags=["café", "strasse"])
    assert second.json()["tags"] == first.json()["tags"]
    assert all(t["box_count"] == 2 for t in client.get("/api/v1/tags").json()["items"])
    changed = patch(client, box_url(first), {"name": "Renamed"})
    assert changed.json()["tags"] == first.json()["tags"]
    cleared = patch(client, box_url(first), {"tags": []})
    assert cleared.json()["tags"] == []
    archive(client, second)
    assert all(t["box_count"] == 0 for t in client.get("/api/v1/tags").json()["items"])


def test_many_to_many_itemization_preserves_sources_unknown_quantities_units(client):
    a, b = box(client, "Attic"), box(client, "Basement")
    inventory = []
    for source, quantity, unit in ((a, None, "pieces"), (a, "2.125", "kg"), (b, "7", "boxes")):
        response = client.post(
            box_url(source) + "/items",
            json={
                "name": "Same item",
                "quantity": quantity,
                "unit": unit,
                "notes_markdown": "**Known** source",
            },
        )
        assert response.status_code == 201, response.text
        inventory.append(response.json())
    one = collection(client, box_codes=[a.json()["code"], b.json()["code"], a.json()["code"]])
    two = collection(client, "Workshop", box_codes=[a.json()["code"]])
    value = client.get(collection_url(one)).json()
    assert value["box_count"] == 2 and value["item_count"] == 3
    assert {row["item"]["id"] for row in value["items"]} == {item["id"] for item in inventory}
    assert len({row["item"]["id"] for row in value["items"]}) == 3
    assert {row["item"]["unit"] for row in value["items"]} == {"pieces", "kg", "boxes"}
    for row in value["items"]:
        assert row["item"] == next(item for item in inventory if item["id"] == row["item"]["id"])
        assert row["box_code"] == row["item"]["box_code"]
        assert row["box_lifecycle"] == "active"
        assert row["box_name"] == ("Attic" if row["box_code"] == a.json()["code"] else "Basement")
    assert len(client.get(box_url(a)).json()["collections"]) == 2
    assert client.get(collection_url(two)).json()["item_count"] == 2
    removed = client.delete(
        "/api/v1/items/" + inventory[1]["id"],
        headers={
            "If-Match": etag("item", inventory[1]["id"], inventory[1]["version"]),
        },
    )
    assert removed.status_code == 204
    assert client.get(collection_url(one)).json()["item_count"] == 2


def test_collection_membership_both_directions_versions_omission_and_clear(client):
    one, two = collection(client), collection(client, "Camping")
    a = box(client, collection_ids=[one.json()["id"], one.json()["id"].upper()])
    assert len(a.json()["collections"]) == 1
    before = client.get(collection_url(one))
    assert before.json()["version"] == 2 and before.json()["box_count"] == 1
    moved = patch(client, box_url(a), {"collection_ids": [two.json()["id"]]})
    assert moved.json()["version"] == a.json()["version"] + 1
    assert client.get(collection_url(one)).json()["version"] == before.json()["version"] + 1
    assert client.get(collection_url(one)).json()["box_count"] == 0
    omitted = patch(client, box_url(a), {"tags": ["Trip"]})
    assert omitted.json()["collections"] == moved.json()["collections"]
    before_box = client.get(box_url(a))
    cleared = patch(client, collection_url(two), {"box_codes": []})
    assert cleared.json()["box_count"] == 0
    after_box = client.get(box_url(a))
    assert after_box.json()["collections"] == []
    assert after_box.json()["version"] == before_box.json()["version"] + 1
    added = patch(client, collection_url(one), {"box_codes": [a.json()["code"]]})
    assert added.json()["box_count"] == 1
    retained = patch(client, collection_url(one), {"description": "Supplies"})
    assert [b["code"] for b in retained.json()["boxes"]] == [a.json()["code"]]
    clear_box = patch(client, box_url(a), {"collection_ids": []})
    assert clear_box.json()["collections"] == [] and clear_box.json()["tags"] == omitted.json()["tags"]
    assert client.get(collection_url(one)).json()["box_count"] == 0


def test_collection_rename_updates_refs_etags_and_search_projection(client):
    a = box(client)
    c = collection(client, "Expedition", box_codes=[a.json()["code"]])
    before = client.get(box_url(a))
    renamed = patch(client, collection_url(c), {"name": "Voyage"})
    assert renamed.status_code == 200
    current = client.get(box_url(a))
    assert current.headers["etag"] != before.headers["etag"]
    assert current.json()["collections"] == [{"id": c.json()["id"], "name": "Voyage"}]
    assert codes(client.get("/api/v1/search?q=Expedition"), True) == set()
    found = client.get("/api/v1/search?q=Voyage")
    assert codes(found, True) == {a.json()["code"]}
    assert found.json()["items"][0]["matched_fields"] == ["collection"]
    assert found.json()["items"][0]["matches"][0]["field"] == "collection"
    stale = client.patch(box_url(a), json={"tags": ["Stale"]}, headers={"If-Match": before.headers["etag"]})
    assert stale.status_code == 412
    with client.app.state.services.database.transaction() as repo:
        assert verify_search(repo)["mismatches"] == 0


def test_search_and_exact_filters_intersect_tags_contents_collections(client):
    c = collection(client, "Expedition")
    a = box(client, "First", tags=["Fragile"], collection_ids=[c.json()["id"]])
    b = box(client, "Second", tags=["Fragile"])
    other = box(client, "Third", tags=["Winter"], collection_ids=[c.json()["id"]])
    for source in (a, b, other):
        assert client.post(box_url(source) + "/items", json={"name": "Cables"}).status_code == 201
    tag_id = a.json()["tags"][0]["id"]
    filters = {"tag_id": tag_id, "collection_id": c.json()["id"]}
    assert codes(client.get("/api/v1/boxes", params=filters)) == {a.json()["code"]}
    assert codes(client.get("/api/v1/search", params={"q": "cables", **filters}), True) == {a.json()["code"]}
    result = client.get("/api/v1/search", params={"q": "Fragile cables"})
    assert codes(result, True) == {a.json()["code"], b.json()["code"]}
    assert all({"tag", "item_name"} <= set(r["matched_fields"]) for r in result.json()["items"])
    assert codes(client.get("/api/v1/search", params={"q": "Expedition cables"}), True) == {
        a.json()["code"],
        other.json()["code"],
    }
    assert codes(client.get("/api/v1/boxes", params={"tag_id": str(uuid.uuid4())})) == set()
    assert client.get("/api/v1/boxes", params={"collection_id": "bad"}).status_code == 422
    assert client.get("/api/v1/collections?q=cables").json()["items"] == []
    assert client.get("/api/v1/collections?q=EXPED").json()["items"][0]["id"] == c.json()["id"]
    patch(client, collection_url(c), {"description": "Contains 100% items"})
    assert len(client.get("/api/v1/collections?q=100%25").json()["items"]) == 1
    assert client.get("/api/v1/collections?q=_").json()["items"] == []


@pytest.mark.parametrize("path", ["/api/v1/boxes", "/api/v1/search"])
def test_filter_bound_cursors_and_invalid_projection_exact_code(client, path):
    c = collection(client)
    sources = [box(client, tags=["Fragile"], collection_ids=[c.json()["id"]]) for _ in range(3)]
    tag_id = sources[0].json()["tags"][0]["id"]
    params = {"tag_id": tag_id, "collection_id": c.json()["id"], "limit": 1}
    if path.endswith("search"):
        params["q"] = "Fragile"
    page = client.get(path, params=params)
    cursor = page.json()["page"]["next_cursor"]
    assert cursor
    next_page = client.get(path, params={**params, "cursor": cursor})
    assert next_page.status_code == 200
    assert codes(page, path.endswith("search")).isdisjoint(codes(next_page, path.endswith("search")))
    for key in ("tag_id", "collection_id"):
        changed = client.get(path, params={**params, key: str(uuid.uuid4()), "cursor": cursor})
        assert changed.status_code == 422 and changed.json()["code"] == "cursor.invalid"
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.update("search_projection_state", {"state": "invalid"}, singleton=1)
    query = {"q": sources[0].json()["code"], "tag_id": tag_id, "collection_id": c.json()["id"]}
    assert codes(client.get("/api/v1/search", params=query), True) == {sources[0].json()["code"]}
    assert codes(client.get("/api/v1/search", params={**query, "tag_id": str(uuid.uuid4())}), True) == set()


def test_archive_members_always_listed_itemization_opt_in_and_membership_readonly(client):
    a, b = box(client, tags=["Fragile"]), box(client, "Other")
    for source in (a, b):
        assert client.post(box_url(source) + "/items", json={"name": "Part"}).status_code == 201
    c = collection(client, box_codes=[a.json()["code"], b.json()["code"]])
    before = client.get(collection_url(c))
    archive(client, a)
    current = client.get(collection_url(c))
    assert current.json()["version"] == before.json()["version"] + 1
    assert (
        current.json()["box_count"]
        == current.json()["archived_box_count"]
        == current.json()["item_count"]
        == 1
    )
    assert len(current.json()["boxes"]) == 2 and len(current.json()["items"]) == 1
    inclusive = client.get(collection_url(c), params={"include_archived": "true"})
    assert len(inclusive.json()["items"]) == 2
    assert {i["box_lifecycle"] for i in inclusive.json()["items"]} == {"active", "archived"}
    assert client.get("/api/v1/tags").json()["items"][0]["box_count"] == 0
    assert codes(client.get("/api/v1/search?q=Fragile"), True) == set()
    assert codes(client.get("/api/v1/search?q=Fragile&include_archived=true"), True) == {a.json()["code"]}
    kept = patch(client, collection_url(c), {"box_codes": [a.json()["code"]], "name": "Retained"})
    assert kept.status_code == 200 and kept.json()["archived_box_count"] == 1
    before = snapshot(client)
    rejected = patch(client, collection_url(c), {"box_codes": [], "name": "Should roll back"})
    assert rejected.status_code == 409 and rejected.json()["code"] == "box.archived"
    assert snapshot(client) == before
    empty = collection(client, "Empty")
    rejected = patch(client, collection_url(empty), {"box_codes": [a.json()["code"]]})
    assert rejected.status_code == 409
    assert patch(client, box_url(a), {"tags": []}).status_code == 409
    assert patch(client, box_url(a), {"collection_ids": []}).status_code == 409
    archived = client.get(box_url(a))
    restored = client.post(box_url(a) + "/restore", headers={"If-Match": archived.headers["etag"]})
    assert restored.status_code == 200
    assert client.get(collection_url(c)).json()["box_count"] == 1


def test_collection_delete_dissolves_only_and_purge_removes_memberships(client):
    a = box(client, tags=["Keepsake"])
    item = client.post(box_url(a) + "/items", json={"name": "Part", "quantity": None}).json()
    c = collection(client, box_codes=[a.json()["code"]])
    other = collection(client, "Other", box_codes=[a.json()["code"]])
    archive(client, a)
    before = client.get(box_url(a))
    current = client.get(collection_url(c))
    assert client.delete(collection_url(c), headers={"If-Match": current.headers["etag"]}).status_code == 204
    after = client.get(box_url(a))
    assert after.json()["version"] == before.json()["version"] + 1
    assert after.json()["items"] == [item] and after.json()["tags"] == a.json()["tags"]
    assert after.json()["collections"] == [{"id": other.json()["id"], "name": "Other"}]
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.insert(
            "backups",
            {
                "id": new_id(),
                "status": "verified",
                "relative_path": "fixture-only",
                "format_version": 1,
                "schema_version": "0002",
                "requested_by": repo.find("users", role="owner")[0]["id"],
                "created_at": now(),
                "verified_at": now(),
            },
        )
    purged = client.post(
        box_url(a) + "/purge",
        json={"confirmation_code": a.json()["code"]},
        headers={"If-Match": after.headers["etag"]},
    )
    assert purged.status_code == 204, purged.text
    remaining = client.get(collection_url(other)).json()
    assert remaining["boxes"] == remaining["items"] == []
    assert remaining["box_count"] == remaining["archived_box_count"] == remaining["item_count"] == 0
    assert client.get("/api/v1/tags").json()["items"][0]["box_count"] == 0
    with client.app.state.services.database.transaction() as repo:
        assert repo.find("box_tags") == repo.find("collection_boxes") == []
        assert verify_search(repo)["mismatches"] == 0


@pytest.mark.parametrize(
    "mode", ["create_box", "patch_box", "create_collection", "patch_collection", "duplicate"]
)
def test_unknown_references_and_name_conflicts_rollback_everything(client, mode):
    a = box(client, tags=["Old"])
    c = collection(client, box_codes=[a.json()["code"]])
    other = collection(client, "Existing")
    before = snapshot(client)
    if mode in {"create_box", "patch_box"}:
        body = {
            "name": "Changed",
            "tags": ["Must roll back"],
            "collection_ids": [c.json()["id"], str(uuid.uuid4())],
        }
        response = (
            client.post("/api/v1/boxes", json=body)
            if mode == "create_box"
            else patch(client, box_url(a), body)
        )
    elif mode in {"create_collection", "patch_collection"}:
        body = {"name": "Changed", "box_codes": [a.json()["code"], BoxCode.generate().value]}
        response = (
            client.post("/api/v1/collections", json=body)
            if mode == "create_collection"
            else patch(client, collection_url(c), body)
        )
    else:
        response = patch(client, collection_url(c), {"name": other.json()["name"].upper(), "box_codes": []})
    assert response.status_code == (409 if mode == "duplicate" else 404), response.text
    assert snapshot(client) == before


@pytest.mark.parametrize("name", ["cafe\u0301", " CAFÉ "])
def test_collection_names_are_canonical_unique(client, name):
    collection(client, "Café")
    response = client.post("/api/v1/collections", json={"name": name})
    assert response.status_code == 409 and response.json()["code"] == "collection.name_conflict"
    collection(client, "Straße")
    assert client.post("/api/v1/collections", json={"name": "STRASSE"}).status_code == 409


@pytest.mark.parametrize(
    "resource,fields",
    [
        ("boxes", {"tags": [""]}),
        ("boxes", {"tags": ["  "]}),
        ("boxes", {"tags": ["bad\x00"]}),
        ("boxes", {"tags": ["a" * 65]}),
        ("boxes", {"tags": ["tag"] * 33}),
        ("boxes", {"collection_ids": [str(uuid.uuid4())] * 101}),
        ("boxes", {"collection_ids": ["bad"]}),
        ("boxes", {"tags": None}),
        ("boxes", {"collection_ids": None}),
        ("collections", {"name": " "}),
        ("collections", {"name": "a" * 121}),
        ("collections", {"description": "a" * 2001}),
        ("collections", {"description": "bad\x00"}),
        ("collections", {"box_codes": [BoxCode.generate().value] * 501}),
        ("collections", {"box_codes": None}),
        ("collections", {"unexpected": "field"}),
    ],
)
def test_request_limits_and_types(client, resource, fields):
    response = client.post("/api/v1/" + resource, json={"name": "Valid", **fields})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_collection_preconditions_stale_atomicity_and_idempotent_retries(client, method):
    a = box(client)
    c = collection(client, box_codes=[a.json()["code"]])
    url = collection_url(c)
    body = {"name": "Renamed", "box_codes": []}
    request = getattr(client, method)
    kwargs = {"json": body} if method == "patch" else {}
    assert request(url, **kwargs).status_code == 428
    stale = c.headers["etag"]
    patch(client, box_url(a), {"tags": ["Updated"]})
    before = snapshot(client)
    assert request(url, headers={"If-Match": stale}, **kwargs).status_code == 412
    assert snapshot(client) == before
    current = client.get(url)
    headers = {"If-Match": current.headers["etag"], "Idempotency-Key": str(uuid.uuid4())}
    first = request(url, headers=headers, **kwargs)
    after = snapshot(client)
    repeated = request(url, headers=headers, **kwargs)
    assert first.status_code == repeated.status_code == (200 if method == "patch" else 204)
    assert first.content == repeated.content and first.headers.get("etag") == repeated.headers.get("etag")
    assert snapshot(client) == after
    if method == "patch":
        conflict = request(url, headers=headers, json={"name": "Different"})
        assert conflict.status_code == 409
        assert snapshot(client) == after


def test_creation_and_box_membership_replay(client):
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/api/v1/collections", json={"name": "Retry"}, headers=headers)
    replay = client.post("/api/v1/collections", json={"name": "Retry"}, headers=headers)
    assert first.status_code == replay.status_code == 201 and first.json() == replay.json()
    a = box(client)
    headers = {"If-Match": a.headers["etag"], "Idempotency-Key": str(uuid.uuid4())}
    body = {"tags": ["Retry"], "collection_ids": [first.json()["id"]]}
    changed = client.patch(box_url(a), json=body, headers=headers)
    state = snapshot(client)
    replay = client.patch(box_url(a), json=body, headers=headers)
    assert changed.status_code == replay.status_code == 200 and changed.json() == replay.json()
    assert snapshot(client) == state


def test_anonymous_editor_viewer_auth_csrf_and_replay_role_checks(client, settings):
    settings.anonymous_access = "editor"
    with browser(client.app, settings.origin) as visitor:
        assert visitor.get("/api/v1/tags").status_code == 401
        assert visitor.get("/api/v1/collections").status_code == 401
        session(visitor)
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        response = visitor.post("/api/v1/collections", json={"name": "Guest"}, headers=headers)
        assert response.status_code == 201
        a = box(visitor, tags=["Guest"], collection_ids=[response.json()["id"]])
        assert visitor.get(collection_url(response)).json()["box_count"] == 1
        for method, url, body in (
            ("POST", "/api/v1/collections", {"name": "Forbidden"}),
            ("PATCH", collection_url(response), {"name": "Forbidden"}),
            ("DELETE", collection_url(response), None),
            ("PATCH", box_url(a), {"tags": []}),
        ):
            current = visitor.get(url if method != "POST" else collection_url(response))
            denied = visitor.request(
                method, url, json=body, headers={"X-CSRF-Token": "wrong", "If-Match": current.headers["etag"]}
            )
            assert denied.status_code == 403
        settings.anonymous_access = "viewer"
        assert visitor.get("/api/v1/tags").status_code == 200
        assert visitor.get(collection_url(response)).status_code == 200
        assert visitor.post("/api/v1/collections", json={"name": "Guest"}, headers=headers).status_code == 403
        assert patch(visitor, box_url(a), {"tags": []}).status_code == 403
        assert patch(visitor, collection_url(response), {"box_codes": []}).status_code == 403
        current = visitor.get(collection_url(response))
        assert (
            visitor.delete(
                collection_url(response), headers={"If-Match": current.headers["etag"]}
            ).status_code
            == 403
        )
