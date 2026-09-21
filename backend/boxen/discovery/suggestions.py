"""Small, local suggestions from confirmed source data, independent of the FTS projection."""

import re
import unicodedata
from heapq import nsmallest
from itertools import zip_longest
from uuid import UUID

from boxen.discovery.infrastructure.search import FILTERS

VISIBLE = f"(:include=1 OR b.lifecycle='active') AND {FILTERS}"
CODE_CHAR = "[0-9A-HJKMNP-TV-Z]"
SOURCE_QUERIES = (
    (
        "item",
        f"SELECT i.id,i.name AS label,b.name AS box_name,b.public_code AS box_code "
        f"FROM inventory_items i JOIN boxes b ON b.id=i.box_id "
        f"WHERE i.lifecycle='active' AND {VISIBLE}",
    ),
    (
        "tag",
        f"SELECT t.id,t.name AS label,count(*) AS box_count FROM tags t "
        f"JOIN box_tags bt ON bt.tag_id=t.id JOIN boxes b ON b.id=bt.box_id "
        f"WHERE {VISIBLE} GROUP BY t.id",
    ),
    (
        "collection",
        f"SELECT c.id,c.name AS label,count(*) AS box_count FROM collections c "
        f"JOIN collection_boxes cb ON cb.collection_id=c.id JOIN boxes b ON b.id=cb.box_id "
        f"WHERE {VISIBLE} GROUP BY c.id",
    ),
)


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value.casefold())


def tokens(value: str) -> list[str]:
    """Keep Unicode letters/numbers and their combining marks together."""
    words, word = [], ""
    for character in normalized(value):
        if character.isalnum() or (word and unicodedata.category(character).startswith("M")):
            word += character
        elif word:
            words.append(word)
            word = ""
    if word:
        words.append(word)
    return words


def suggestion_intent(raw: str) -> tuple[str, str, str]:
    query = unicodedata.normalize("NFC", raw.strip())
    upper = query.upper()
    if upper == "BX" or upper.startswith("BX-"):
        payload = upper[3:].translate(str.maketrans("OIL", "011"))
        if not query.isascii() or not re.fullmatch(
            rf"(?:{CODE_CHAR}{{2,8}}|{CODE_CHAR}{{4}}-{CODE_CHAR}{{0,4}})", payload
        ):
            return query, "none", ""
        payload = payload.replace("-", "")
        prefix = "BX-" + payload[:4] + ("-" + payload[4:] if len(payload) > 4 else "")
        return query, "box_code", prefix
    if sum(character.isalnum() for character in query) < 2:
        return query, "none", ""
    return query, "text", ""


def suggest_search(repo, params: dict, actor) -> dict:
    actor.authorize("viewer")
    query, kind, prefix = suggestion_intent(params["q"])
    result: dict = {"query": query, "kind": kind, "suggestions": []}
    if kind == "none":
        return result
    limit = params.get("limit", 8)
    values = {
        "include": int(params.get("include_archived", False)),
        **{key: str(UUID(params[key])) if params.get(key) else None for key in ("tag_id", "collection_id")},
    }
    if kind == "box_code":
        # Intent parsing admits only canonical code characters, never LIKE wildcards.
        result["suggestions"] = repo.rows(
            f"SELECT 'box' AS kind,b.id,b.public_code AS label,b.name AS detail,b.public_code AS box_code "
            f"FROM boxes b WHERE b.public_code LIKE :prefix AND {VISIBLE} "
            f"ORDER BY b.public_code,b.id LIMIT :limit",
            {**values, "prefix": prefix + "%", "limit": limit},
        )
        return result

    terms = tokens(query)

    def candidates(source_kind, sql):
        # Stream source rows and retain at most `limit` matches per type. This small-app
        # path avoids SQLite's ASCII-only case folding and never queries draft observations.
        for row in repo.execute(sql, values).mappings():
            words = tokens(row["label"])
            if not all(any(word.startswith(term) for word in words) for term in terms):
                continue
            detail = (
                row["box_name"] + " · " + row["box_code"]
                if source_kind == "item"
                else f"{row['box_count']} {'box' if row['box_count'] == 1 else 'boxes'}"
            )
            yield {
                "kind": source_kind,
                "id": row["id"],
                "label": row["label"],
                "detail": detail,
                "box_code": row["box_code"] if source_kind == "item" else None,
            }

    groups = [
        nsmallest(
            limit,
            candidates(source_kind, sql),
            key=lambda row: (normalized(row["label"]), normalized(row["detail"]), row["id"]),
        )
        for source_kind, sql in SOURCE_QUERIES
    ]
    # Stable round-robin gives each matching type room under the shared response limit.
    result["suggestions"] = [row for group in zip_longest(*groups) for row in group if row is not None][
        :limit
    ]
    return result
