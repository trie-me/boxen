import unicodedata
import uuid
from pathlib import Path

import pytest
from boxen.catalog.domain import ALPHABET, BoxCode
from boxen.discovery.suggestions import suggestion_intent
from boxen.platform.contracts import api_contract, validate_payload
from boxen.shared.errors import DomainError
from conftest import SUCCESSES
from test_ai_operations import analysis_fixture
from test_anonymous_access import browser, session
from test_organization import archive, box, box_url, collection, collection_url, patch, snapshot

URL = "/api/v1/search/suggestions"


def suggest(client, query, **params):
    response = client.get(URL, params={"q": query, **params})
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {"query", "kind", "suggestions"}
    assert value["query"] == unicodedata.normalize("NFC", query.strip())
    assert len(value["suggestions"]) <= params.get("limit", 8)
    for row in value["suggestions"]:
        assert set(row) == {"kind", "id", "label", "detail", "box_code"}
        assert str(uuid.UUID(row["id"])) == row["id"]
        assert row["label"] and row["detail"]
        if row["kind"] in {"tag", "collection"}:
            assert row["box_code"] is None
        else:
            assert BoxCode.parse(row["box_code"]).value == row["box_code"]
    return value


def item(client, source, name, **fields):
    response = client.post(box_url(source) + "/items", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response


def box_id(client, source):
    # Existing box responses expose the public code, not the internal UUID.
    with client.app.state.services.database.transaction() as repo:
        return repo.one("boxes", public_code=source.json()["code"])["id"]


def coded_box(client, monkeypatch, payload, name="Workshop", **fields):
    with monkeypatch.context() as scoped:
        scoped.setattr(BoxCode, "generate", lambda: BoxCode.from_payload(payload))
        return box(client, name, **fields)


@pytest.mark.parametrize(
    "query",
    [
        "",
        " ",
        "\t\n",
        "a",
        "1",
        "é",
        "e\u0301",
        "ß",
        "क्",
        "🧰",
        "%%__*",
        "a - 🧰",
        "BX",
        "bx",
        " BX ",
        "BX-",
        "BX-a",
        "BX-1",
        "BX-O",
        "BX-ß",
        "BX-ıa",
        "BX-ſa",
        "BX-ＡＢ",
        "BX-١٢",
        "BX-AB_",
        "BX-AB%",
        "BX-AB*",
        "BX-AB CD",
        "BX-AB--CD",
        "BX-AB-CD",
        "BX-ABC-D",
        "BX-ABCDE-F",
        "BX--AB",
        "BX-ABCD--",
        "BX-ABCD-EFGH-",
        "BX-ABCDEFGHJ",
        "BX-U1",
        "BX-AB🧰",
        "BX-AB\n",
        "BX-AB\x00",
    ],
)
def test_ineligible_and_malformed_intent(query):
    # A trailing newline is trimmed before recognition, just like surrounding spaces.
    expected = "box_code" if query == "BX-AB\n" else "none"
    assert suggestion_intent(query)[1] == expected


@pytest.mark.parametrize(
    "query,prefix",
    [
        ("BX-AB", "BX-AB"),
        (" bx-ab ", "BX-AB"),
        ("BX-ABC", "BX-ABC"),
        ("BX-ABCD", "BX-ABCD"),
        ("BX-ABCD-", "BX-ABCD"),
        ("BX-ABCDE", "BX-ABCD-E"),
        ("BX-ABCDEFGH", "BX-ABCD-EFGH"),
        ("BX-ABCD-EFGH", "BX-ABCD-EFGH"),
        ("bx-oil", "BX-011"),
        ("BX-OIL1-OIL1", "BX-0111-0111"),
    ],
)
def test_code_intent_aliases_and_optional_middle_hyphen(query, prefix):
    assert suggestion_intent(query) == (query.strip(), "box_code", prefix)


@pytest.mark.parametrize("query", ["ab", "a b", "a1", "12", "工具", "éq", "ᾀβ", "🧰 ab", "BXAB", "BXray"])
def test_text_intent_counts_unicode_letters_and_numbers(query):
    assert suggestion_intent(query)[1:] == ("text", "")


def test_exact_contract_and_empty_success_are_exercised(client):
    assert suggest(client, " ") == {"query": "", "kind": "none", "suggestions": []}
    assert suggest(client, "unmatched") == {"query": "unmatched", "kind": "text", "suggestions": []}
    assert "suggestSearch" in SUCCESSES
    spec = api_contract()
    operation = spec["paths"]["/search/suggestions"]["get"]
    assert operation["operationId"] == "suggestSearch"
    parameters = {p["name"]: p for p in operation["parameters"] if "name" in p}
    assert parameters["q"]["required"] is True
    assert parameters["q"]["schema"] == {"type": "string", "minLength": 1, "maxLength": 256}
    assert parameters["limit"]["schema"] == {"type": "integer", "minimum": 1, "maximum": 12, "default": 8}
    assert parameters["include_archived"]["schema"] == {"type": "boolean", "default": False}
    assert {p["$ref"] for p in operation["parameters"] if "$ref" in p} == {
        "#/components/parameters/TagFilter",
        "#/components/parameters/CollectionFilter",
    }
    schema = spec["components"]["schemas"]["SearchSuggestion"]
    assert schema["additionalProperties"] is False
    assert (
        set(schema["properties"]) == set(schema["required"]) == {"kind", "id", "label", "detail", "box_code"}
    )
    root = Path(__file__).resolve().parents[2]
    assert (root / "backend/boxen/assets/openapi.yaml").read_bytes() == (
        root / "docs/system-design/contracts/openapi.yaml"
    ).read_bytes()


@pytest.mark.parametrize(
    "params,field",
    [
        ({}, "q"),
        ({"q": ""}, "q"),
        ({"q": "a" * 257}, "q"),
        *[({"q": "ab", "limit": value}, "limit") for value in [0, 13, -1, "1.5", "no", ""]],
        *[({"q": "ab", "include_archived": value}, "include_archived") for value in ["1", "yes", ""]],
        *[({"q": "ab", field: "invalid' OR 1=1--"}, field) for field in ["tag_id", "collection_id"]],
    ],
)
def test_request_constraints(client, params, field):
    response = client.get(URL, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["errors"][0]["path"] == "/query/" + field


def test_maximum_query_length_is_accepted(client):
    assert suggest(client, "é" * 256)["kind"] == "text"


def test_code_suggestions_only_match_canonical_prefix_and_real_ids(client, monkeypatch):
    source = coded_box(client, monkeypatch, "0111ABC", "Garage")
    code = source.json()["code"]
    item(client, source, "BX-0111 label")
    other = coded_box(client, monkeypatch, "AB0111C", "BX-0111 name")
    for query in ["BX-01", "bx-oi", "BX-OL", " BX-oil1 ", "BX-0111-", code.lower(), code]:
        result = suggest(client, query)
        assert result["kind"] == "box_code"
        assert result["suggestions"] == [
            {"kind": "box", "id": box_id(client, source), "label": code, "detail": "Garage", "box_code": code}
        ]
    compact_suffix = "BX-" + code[3:].replace("-", "")
    assert suggest(client, compact_suffix)["suggestions"][0]["box_code"] == code
    wrong_check = ALPHABET[(ALPHABET.index(code[-1]) + 1) % len(ALPHABET)]
    wrong = suggest(client, code[:-1] + wrong_check)
    assert wrong["kind"] == "box_code" and wrong["suggestions"] == []
    assert other.json()["code"] != code


@pytest.mark.parametrize(
    "query", ["BX", "BX-", "BX-a", "BX-AB%", "BX-AB_CD", "BX-AB CD", "BX-AB🧰", "BX-ıa", "BX-ßa"]
)
def test_reserved_and_malformed_code_never_falls_through_to_text(client, query):
    source = box(client, query, tags=[query])
    item(client, source, query)
    collection(client, query, box_codes=[source.json()["code"]])
    result = suggest(client, query)
    assert result["kind"] == "none" and result["suggestions"] == []


def test_text_is_word_prefix_only_and_does_not_suggest_box_names_or_notes(client):
    source = box(client, "Screw workshop", tags=["Brass screws"])
    inventory = item(client, source, "Brass screws", notes_markdown="Secretword")
    group = collection(client, "Brass screws", box_codes=[source.json()["code"]])
    item(client, source, "Unscrewed bolts")
    for query in ["screw", " SCREW ", "bra scr", "screw brass"]:
        result = suggest(client, query)
        assert result["kind"] == "text"
        assert [row["kind"] for row in result["suggestions"]] == ["item", "tag", "collection"]
        assert [row["id"] for row in result["suggestions"]] == [
            inventory.json()["id"],
            source.json()["tags"][0]["id"],
            group.json()["id"],
        ]
        assert result["suggestions"][0]["detail"] == "Screw workshop · " + source.json()["code"]
        assert all(row["label"] == "Brass screws" for row in result["suggestions"])
    for query in ["rass", "Secretword", "workshop", "screw missing"]:
        assert suggest(client, query)["suggestions"] == []
    for query in ["Screw workshop", "Secretword"]:
        full = client.get("/api/v1/search", params={"q": query})
        assert full.status_code == 200 and full.json()["items"][0]["box"]["code"] == source.json()["code"]


@pytest.mark.parametrize(
    "name,query",
    [
        ("Café supplies", " cafe\u0301 "),
        ("CAFE\u0301 supplies", "café"),
        ("Straße gear", "STRASS"),
        ("İstanbul gear", "i\u0307sta"),
        ("Σίσυφος gear", "ΣΊΣ"),
        ("工具 набор", "工具"),
        ("Шурупы", "ШУР"),
        ("किताबें", "किता"),
        ("Alpha bolts", "a b"),
        ("12 pack", "12"),
    ],
)
def test_unicode_normalization_casefold_and_token_prefixes_all_text_types(client, name, query):
    source = box(client, tags=[name])
    inventory = item(client, source, name)
    group = collection(client, name, box_codes=[source.json()["code"]])
    result = suggest(client, query)
    assert result["kind"] == "text"
    assert {row["id"] for row in result["suggestions"]} == {
        inventory.json()["id"],
        source.json()["tags"][0]["id"],
        group.json()["id"],
    }


@pytest.fixture
def filtered_sources(client, monkeypatch):
    groups = [
        collection(client, "Screw collection " + name) for name in ["shared", "other", "archive", "unused"]
    ]
    members = [
        coded_box(
            client,
            monkeypatch,
            "ABCD001",
            "Visible",
            tags=["Screw shared", "Screw visible"],
            collection_ids=[groups[0].json()["id"]],
        ),
        coded_box(
            client,
            monkeypatch,
            "ABCD002",
            "Tag only",
            tags=["Screw shared", "Screw other"],
            collection_ids=[groups[1].json()["id"]],
        ),
        coded_box(
            client,
            monkeypatch,
            "ABCD003",
            "Collection only",
            tags=["Screw other"],
            collection_ids=[groups[0].json()["id"]],
        ),
        coded_box(
            client,
            monkeypatch,
            "ABCD004",
            "Archived",
            tags=["Screw shared", "Screw archive"],
            collection_ids=[groups[0].json()["id"], groups[2].json()["id"]],
        ),
    ]
    inventory = [item(client, source, "Screw " + source.json()["name"]) for source in members]
    archive(client, members[3])
    orphan = box(client, tags=["Screw unused"])
    assert patch(client, box_url(orphan), {"tags": []}).status_code == 200
    shared_tag = next(tag for tag in members[0].json()["tags"] if tag["name"] == "Screw shared")
    return members, inventory, groups, shared_tag["id"]


@pytest.mark.parametrize(
    "filtered", ["neither", "tag", "collection", "both", "unknown_tag", "unknown_collection"]
)
@pytest.mark.parametrize("include_archived", [False, True])
def test_filters_and_archive_visibility_apply_to_every_type(
    client, filtered_sources, filtered, include_archived
):
    sources, inventory, groups, tag_id = filtered_sources
    filters = {"include_archived": str(include_archived).lower(), "limit": 12}
    if filtered in {"tag", "both", "unknown_tag"}:
        filters["tag_id"] = str(uuid.uuid4()) if filtered == "unknown_tag" else tag_id.upper()
    if filtered in {"collection", "both", "unknown_collection"}:
        filters["collection_id"] = (
            str(uuid.uuid4()) if filtered == "unknown_collection" else groups[0].json()["id"].upper()
        )
    indexes = {
        "neither": {0, 1, 2, 3},
        "tag": {0, 1, 3},
        "collection": {0, 2, 3},
        "both": {0, 3},
        "unknown_tag": set(),
        "unknown_collection": set(),
    }[filtered]
    if not include_archived:
        indexes -= {3}
    text_rows = suggest(client, "screw", **filters)["suggestions"]
    assert {row["id"] for row in text_rows if row["kind"] == "item"} == {
        inventory[i].json()["id"] for i in indexes
    }
    for kind, refs in [("tag", "tags"), ("collection", "collections")]:
        expected = {ref["id"] for i in indexes for ref in sources[i].json()[refs]}
        assert {row["id"] for row in text_rows if row["kind"] == kind} == expected
        for row in text_rows:
            if row["kind"] == kind:
                count = sum(any(ref["id"] == row["id"] for ref in sources[i].json()[refs]) for i in indexes)
                assert row["detail"] == f"{count} {'box' if count == 1 else 'boxes'}"
    code_rows = suggest(client, "BX-AB", **filters)["suggestions"]
    assert {row["id"] for row in code_rows} == {box_id(client, sources[i]) for i in indexes}
    assert all(row["kind"] == "box" for row in code_rows)


def test_live_membership_and_item_deletion_are_visible_without_projection(client):
    source = box(client, tags=["Screw tag"])
    group = collection(client, "Screw collection", box_codes=[source.json()["code"]])
    inventory = item(client, source, "Screw item")
    assert len(suggest(client, "screw")["suggestions"]) == 3
    removed = client.delete(
        "/api/v1/items/" + inventory.json()["id"], headers={"If-Match": inventory.headers["etag"]}
    )
    assert removed.status_code == 204
    assert patch(client, box_url(source), {"tags": []}).status_code == 200
    assert patch(client, collection_url(group), {"box_codes": []}).status_code == 200
    for include in ["true", "false"]:
        assert suggest(client, "screw", include_archived=include)["suggestions"] == []
    added = item(client, source, "Screw replacement")
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.execute("DELETE FROM box_search")
        repo.update("search_projection_state", {"state": "invalid"}, singleton=1)
    before = snapshot(client)
    assert suggest(client, "screw")["suggestions"][0]["id"] == added.json()["id"]
    assert suggest(client, source.json()["code"])["suggestions"][0]["id"] == box_id(client, source)
    assert snapshot(client) == before
    assert client.get("/api/v1/search", params={"q": "screw"}).status_code == 503


def test_pending_and_rejected_ai_never_suggest_but_accepted_items_do(client):
    app, fake, source, _, _ = analysis_fixture(client)
    template = fake.output["observations"][0]
    fake.output["observations"] = [
        {**template, "name": "Screw pending"},
        {**template, "name": "Screw rejected"},
    ]
    app.analysis.execute(app.analysis.claim("suggestions-test"))
    observations = client.get(f"/api/v1/boxes/{source['code']}/observations").json()["items"]
    assert len(observations) == 2
    rejected = client.post("/api/v1/observations/" + observations[1]["id"] + "/reject", json={})
    assert rejected.status_code == 200
    assert suggest(client, "screw")["suggestions"] == []
    accepted = client.post(
        "/api/v1/observations/" + observations[0]["id"] + "/accept",
        json={"mode": "create", "item": {"name": "Screw reviewed"}},
    )
    assert accepted.status_code == 200 and accepted.json()["item"]["provenance"] == "ai"
    rows = suggest(client, "screw")["suggestions"]
    assert len(rows) == 1 and rows[0]["id"] == accepted.json()["item"]["id"]


def test_anonymous_permissions_match_search_and_off_denies_existing_sessions(client, settings):
    source = box(client)
    inventory = item(client, source, "Brass screws")
    for mode in ["viewer", "editor"]:
        settings.anonymous_access = mode
        with browser(client.app, settings.origin) as visitor:
            assert visitor.get(URL, params={"q": "BX"}).status_code == 401
            session(visitor)
            for path in [URL, "/api/v1/search"]:
                assert visitor.get(path, params={"q": "screw"}).status_code == 200
            response = visitor.get(URL, params={"q": "screw"})
            assert response.json()["suggestions"][0]["id"] == inventory.json()["id"]
            assert response.headers["cache-control"] == "no-store"
            settings.anonymous_access = "off"
            for query in ["screw", "BX", source.json()["code"]]:
                assert visitor.get(URL, params={"q": query}).status_code == 401
            visitor.cookies.clear()
            assert visitor.get(URL, params={"q": "screw"}).status_code == 401


def test_authenticated_viewer_can_suggest_and_disabled_user_cannot(client, settings):
    source = box(client)
    item(client, source, "Brass screws")
    user = client.post(
        "/api/v1/users",
        json={
            "username": "reader",
            "display_name": "Reader",
            "password": "reader-test-passphrase",
            "role": "viewer",
        },
    )
    assert user.status_code == 201
    with browser(client.app, settings.origin) as viewer:
        login = viewer.post(
            "/api/v1/auth/login", json={"username": "reader", "password": "reader-test-passphrase"}
        )
        assert login.status_code == 200
        assert len(suggest(viewer, "screw")["suggestions"]) == 1
        assert viewer.get("/api/v1/search", params={"q": "screw"}).status_code == 200
        disabled = client.patch(
            "/api/v1/users/" + user.json()["id"],
            headers={"If-Match": user.headers["etag"]},
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert viewer.get(URL, params={"q": "screw"}).status_code == 401


def test_limits_fairness_stable_order_and_duplicate_names(client, monkeypatch):
    source = coded_box(
        client, monkeypatch, "AB00001", tags=[f"Screw tag {i:02}" for i in reversed(range(14))]
    )
    items = [item(client, source, "Screw item") for _ in range(14)]
    for i in reversed(range(5)):
        collection(client, f"Screw group {i:02}", box_codes=[source.json()["code"]])
    before = snapshot(client)
    complete = suggest(client, "screw", limit=12)["suggestions"]
    assert len(complete) == 12
    assert [row["kind"] for row in complete] == ["item", "tag", "collection"] * 4
    assert [row["id"] for row in complete if row["kind"] == "item"] == sorted(i.json()["id"] for i in items)[
        :4
    ]
    assert [row["label"] for row in complete if row["kind"] == "tag"] == [
        f"Screw tag {i:02}" for i in range(4)
    ]
    assert suggest(client, "screw")["suggestions"] == complete[:8]
    for limit in [1, 2, 3, 7, 12]:
        assert suggest(client, "screw", limit=limit)["suggestions"] == complete[:limit]
    assert suggest(client, "screw", limit=12)["suggestions"] == complete
    assert snapshot(client) == before
    for i in reversed(range(2, 15)):
        coded_box(client, monkeypatch, f"AB{i:05}")
    codes = suggest(client, "BX-AB", limit=12)["suggestions"]
    assert len(codes) == 12 and [r["label"] for r in codes] == sorted(r["label"] for r in codes)
    assert suggest(client, "BX-AB")["suggestions"] == codes[:8]
    assert suggest(client, "BX-AB", limit=1)["suggestions"] == codes[:1]


def test_sql_and_fts_metacharacters_are_data_not_executable(client):
    source = box(client)
    for name in ["Brass screws", "100% cotton", "under_score driver", "O'Reilly wrench", "semi;colon"]:
        item(client, source, name)
    before = snapshot(client)
    for query in [
        "%",
        "_",
        "*",
        '"',
        "' OR 1=1 --",
        '" OR *',
        "screw' UNION SELECT name FROM users--",
        "screw\x00nope",
        "BX-AB%",
        "BX-AB_",
        "screw NOT brass",
    ]:
        assert suggest(client, query)["suggestions"] == []
    for query, expected in [
        ("100%", "100% cotton"),
        ("under_score", "under_score driver"),
        ("O'Reilly", "O'Reilly wrench"),
        ("semi;col", "semi;colon"),
    ]:
        assert [row["label"] for row in suggest(client, query)["suggestions"]] == [expected]
    assert snapshot(client) == before


def test_success_schema_rejects_extra_fields_and_more_than_twelve_rows(client):
    source = box(client)
    item(client, source, "Brass screws")
    value = suggest(client, "screw")
    for invalid in [
        {**value, "extra": True},
        {**value, "suggestions": [{**value["suggestions"][0], "notes": "unexpected"}]},
        {**value, "suggestions": value["suggestions"] * 13},
    ]:
        with pytest.raises(DomainError):
            validate_payload(invalid, {"$ref": "#/components/schemas/SearchSuggestions"})
