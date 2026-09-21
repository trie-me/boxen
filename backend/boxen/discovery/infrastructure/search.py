import re
import unicodedata

FILTERS = """(:tag_id IS NULL OR EXISTS(SELECT 1 FROM box_tags bt WHERE bt.box_id=b.id AND bt.tag_id=:tag_id))
    AND (:collection_id IS NULL OR EXISTS(SELECT 1 FROM collection_boxes cb WHERE cb.box_id=b.id AND cb.collection_id=:collection_id))"""

INSERT_DOCUMENT = """INSERT INTO box_search(box_id,code,name,description,item_names,item_notes,tag_names,collection_names)
    VALUES(:box_id,:code,:name,:description,:item_names,:item_notes,:tag_names,:collection_names)"""


def source_document(repo, box: dict) -> dict:
    items = sorted(
        repo.find("inventory_items", box_id=box["id"], lifecycle="active"), key=lambda row: row["id"]
    )
    return {
        "box_id": box["id"],
        "code": box["public_code"],
        "name": box["name"],
        "description": box["description_text"],
        "item_names": "\n".join(item["name"] for item in items),
        "item_notes": "\n".join(item["notes_text"] for item in items),
        "tag_names": "\n".join(
            row["name"]
            for row in repo.rows(
                "SELECT t.name FROM tags t JOIN box_tags bt ON bt.tag_id=t.id WHERE bt.box_id=:id ORDER BY t.id",
                {"id": box["id"]},
            )
        ),
        "collection_names": "\n".join(
            row["name"]
            for row in repo.rows(
                "SELECT c.name FROM collections c JOIN collection_boxes cb ON cb.collection_id=c.id "
                "WHERE cb.box_id=:id ORDER BY c.id",
                {"id": box["id"]},
            )
        ),
    }


def project_box(repo, box_id: str) -> None:
    repo.execute("DELETE FROM box_search WHERE box_id=:id", {"id": box_id})
    box = repo.one("boxes", id=box_id)
    if box:
        repo.execute(
            INSERT_DOCUMENT,
            source_document(repo, box),
        )


def search_rows(
    repo,
    query: str,
    include_archived: bool,
    offset: int,
    limit: int,
    snapshot: str,
    exact_code: str | None = None,
    tag_id: str | None = None,
    collection_id: str | None = None,
) -> list[dict]:
    tokens = re.findall(r"\w+", unicodedata.normalize("NFC", query), re.UNICODE)[:30]
    if not tokens:
        return []
    match = " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)
    params = {
        "match": match,
        "include": int(include_archived),
        "offset": offset,
        "limit": limit + 1,
        "snapshot": snapshot,
        "code": exact_code or "",
        "tag_id": tag_id,
        "collection_id": collection_id,
    }
    # SQL and identifiers are fixed; only values are bound. No browser FTS syntax is executed.
    return repo.rows(
        f"""SELECT b.* FROM boxes b LEFT JOIN
        (SELECT box_id,bm25(box_search,0,12,8,2,6,1,5,5) AS rank FROM box_search WHERE box_search MATCH :match) f ON f.box_id=b.id
        WHERE (f.box_id IS NOT NULL OR b.public_code=:code) AND (:include=1 OR b.lifecycle='active') AND b.created_at<=:snapshot
        AND {FILTERS}
        ORDER BY (b.public_code=:code) DESC, f.rank, b.id LIMIT :limit OFFSET :offset""",
        params,
    )


def list_boxes(
    repo,
    lifecycle: str,
    sort: str,
    offset: int,
    limit: int,
    snapshot: str,
    tag_id: str | None = None,
    collection_id: str | None = None,
) -> list[dict]:
    order = {
        "updated_desc": "updated_at DESC,id DESC",
        "created_desc": "created_at DESC,id DESC",
        "name_asc": "name COLLATE NOCASE,id",
    }[sort]
    return repo.rows(
        f"SELECT b.* FROM boxes b WHERE (:life='all' OR lifecycle=:life) AND created_at<=:snapshot AND {FILTERS} ORDER BY {order} LIMIT :limit OFFSET :offset",
        {
            "life": lifecycle,
            "snapshot": snapshot,
            "limit": limit + 1,
            "offset": offset,
            "tag_id": tag_id,
            "collection_id": collection_id,
        },
    )


def verify_search(repo, rebuild: bool = False) -> dict:
    source = {box["id"]: source_document(repo, box) for box in repo.find("boxes")}
    actual = repo.rows("SELECT * FROM box_search")
    actual_map = {row["box_id"]: row for row in actual}
    mismatches = (
        sum(actual_map.get(key) != value for key, value in source.items())
        + len(set(actual_map) - set(source))
        + len(actual)
        - len(actual_map)
    )
    if rebuild:
        repo.execute("DELETE FROM box_search")
        for row in source.values():
            repo.execute(
                INSERT_DOCUMENT,
                row,
            )
    return {
        "source_count": len(source),
        "projection_count": len(actual),
        "mismatches": mismatches,
        "rebuilt": rebuild,
    }
