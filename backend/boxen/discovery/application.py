import base64
import hashlib
import hmac
import json
import re
import unicodedata
from uuid import UUID

from boxen.catalog.domain import BoxCode
from boxen.discovery.infrastructure.search import FILTERS, search_rows
from boxen.shared.errors import DomainError
from boxen.shared.values import now


class Pagination:
    def __init__(self, secret: bytes):
        self.secret = secret

    def decode(self, cursor: str | None, scope: str) -> tuple[int, str]:
        if not cursor:
            return 0, now()
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.secret, body, "sha256")):
                raise ValueError
            data = json.loads(body)
            if (
                data["scope"] != hashlib.sha256(scope.encode()).hexdigest()
                or not isinstance(data["offset"], int)
                or not 0 <= data["offset"] <= 1_000_000
            ):
                raise ValueError
            return data["offset"], data["snapshot"]
        except (ValueError, KeyError, TypeError):
            raise DomainError(
                "cursor.invalid", "This page cursor is invalid. Start from the first page."
            ) from None

    def page(self, has_more: bool, offset: int, limit: int, snapshot: str, scope: str) -> dict:
        cursor = None
        if has_more:
            body = json.dumps(
                {
                    "offset": offset + limit,
                    "snapshot": snapshot,
                    "scope": hashlib.sha256(scope.encode()).hexdigest(),
                },
                separators=(",", ":"),
            ).encode()
            cursor = (
                base64.urlsafe_b64encode(body + hmac.digest(self.secret, body, "sha256")).decode().rstrip("=")
            )
        return {"has_more": has_more, "next_cursor": cursor}


def search(repo, params: dict, actor, pagination: Pagination, catalog) -> dict:
    query = unicodedata.normalize("NFC", params["q"].strip())
    params = {
        **params,
        **{key: str(UUID(params[key])) for key in ("tag_id", "collection_id") if params.get(key)},
    }
    if not query:
        raise DomainError("search.empty", "Enter a box name, code, or item.")
    scope = json.dumps({k: v for k, v in params.items() if k not in {"cursor", "limit"}}, sort_keys=True)
    offset, snapshot = pagination.decode(params.get("cursor"), scope)
    limit = params.get("limit", 50)
    try:
        code = BoxCode.parse(query).value
    except DomainError:
        code = None
    state = repo.one("search_projection_state", singleton=1)
    if state["state"] == "invalid" and not code:
        raise DomainError(
            "search.unavailable", "Search needs repair. You can still open a box by its code.", 503
        )
    if state["state"] == "invalid" and code:
        boxes = repo.rows(
            f"SELECT b.* FROM boxes b WHERE public_code=:code AND (:include=1 OR lifecycle='active') "
            f"AND created_at<=:snapshot AND {FILTERS} LIMIT :limit OFFSET :offset",
            {
                "code": code,
                "include": int(params.get("include_archived", False)),
                "limit": limit + 1,
                "offset": offset,
                "snapshot": snapshot,
                "tag_id": params.get("tag_id"),
                "collection_id": params.get("collection_id"),
            },
        )
    else:
        boxes = search_rows(
            repo,
            query,
            params.get("include_archived", False),
            offset,
            limit,
            snapshot,
            code,
            params.get("tag_id"),
            params.get("collection_id"),
        )
    terms = re.findall(r"\w+", query.casefold())
    results = []
    for box in boxes[:limit]:
        items = repo.find("inventory_items", box_id=box["id"], lifecycle="active")
        values = [
            ("code", box["public_code"]),
            ("name", box["name"]),
            ("description", box["description_text"]),
        ]
        values += [("item_name", i["name"]) for i in items] + [("item_notes", i["notes_text"]) for i in items]
        summary = catalog.summary(repo, box, actor)
        values += [("tag", tag["name"]) for tag in summary["tags"]]
        values += [("collection", collection["name"]) for collection in summary["collections"]]
        matches = []
        for field, value in values:
            positions = [value.casefold().find(term) for term in terms if term in value.casefold()]
            if not positions:
                continue
            start = max(0, min(positions) - 60)
            snippet = value[start : start + 240]
            ranges = []
            for term in terms:
                for match in re.finditer(re.escape(term), snippet, re.IGNORECASE):
                    ranges.append({"start": match.start(), "end": match.end()})
            matches.append({"field": field, "snippet": snippet, "ranges": ranges})
        matching = [
            i for i in items if any(t in (i["name"] + " " + i["notes_text"]).casefold() for t in terms)
        ]
        results.append(
            {
                "box": summary,
                "exact_code": box["public_code"] == code,
                "matched_fields": sorted({m["field"] for m in matches}),
                "matches": matches[:8],
                "matching_items": [catalog.item_view(i, box["public_code"]) for i in matching[:5]],
            }
        )
    return {
        "query": query,
        "items": results,
        "page": pagination.page(len(boxes) > limit, offset, limit, snapshot, scope),
    }
