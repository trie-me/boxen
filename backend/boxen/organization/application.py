"""Tags and named collections; inventory remains owned by its original box."""

import unicodedata
from uuid import UUID

from boxen.catalog.domain import Box, BoxCode
from boxen.discovery.infrastructure.search import project_box
from boxen.shared.errors import require
from boxen.shared.values import check_etag, etag, new_id, now, text_value


def canonical_name(value: str, maximum: int, label: str) -> tuple[str, str]:
    name = text_value(unicodedata.normalize("NFC", value), maximum, label)
    return name, unicodedata.normalize("NFC", name.casefold())


def box_refs(repo, box_id: str) -> dict:
    return {
        "tags": repo.rows(
            "SELECT t.id,t.name FROM tags t JOIN box_tags bt ON bt.tag_id=t.id "
            "WHERE bt.box_id=:id ORDER BY t.normalized_name,t.id",
            {"id": box_id},
        ),
        "collections": repo.rows(
            "SELECT c.id,c.name FROM collections c JOIN collection_boxes cb ON cb.collection_id=c.id "
            "WHERE cb.box_id=:id ORDER BY c.normalized_name,c.id",
            {"id": box_id},
        ),
    }


def touch_collections(repo, ids) -> None:
    for collection_id in sorted(set(ids)):
        repo.execute(
            "UPDATE collections SET version=version+1,updated_at=:at WHERE id=:id",
            {"id": collection_id, "at": now()},
        )


def set_box_organization(repo, box: dict, body: dict) -> None:
    """Caller owns the box/collection versions and the surrounding transaction."""
    if "tags" in body:
        tags: dict[str, str] = {}
        for value in body["tags"]:
            name, normalized = canonical_name(value, 64, "Tag name")
            tags.setdefault(normalized, name)
        repo.delete("box_tags", box_id=box["id"])
        for normalized, name in tags.items():
            tag = repo.one("tags", normalized_name=normalized)
            if tag is None:
                tag = {"id": new_id(), "name": name, "normalized_name": normalized, "created_at": now()}
                repo.insert("tags", tag)
            repo.insert("box_tags", {"box_id": box["id"], "tag_id": tag["id"]})
    if "collection_ids" in body:
        ids = {str(UUID(value)) for value in body["collection_ids"]}
        for collection_id in ids:
            require(
                repo.one("collections", id=collection_id) is not None,
                "collection.not_found",
                "A selected collection no longer exists.",
                404,
            )
        repo.delete("collection_boxes", box_id=box["id"])
        for collection_id in sorted(ids):
            repo.insert("collection_boxes", {"collection_id": collection_id, "box_id": box["id"]})


class Organization:
    def __init__(self, catalog):
        self.catalog = catalog

    def load(self, repo, collection_id: str) -> dict:
        row = repo.one("collections", id=str(UUID(collection_id)))
        require(row is not None, "collection.not_found", "Collection not found.", 404)
        return row

    @staticmethod
    def members(repo, collection_id: str) -> list[dict]:
        return repo.rows(
            "SELECT b.* FROM boxes b JOIN collection_boxes cb ON cb.box_id=b.id "
            "WHERE cb.collection_id=:id ORDER BY b.name COLLATE NOCASE,b.public_code",
            {"id": collection_id},
        )

    def summary(self, repo, row: dict) -> dict:
        boxes = self.members(repo, row["id"])
        active = [box for box in boxes if box["lifecycle"] == "active"]
        return {
            **{key: row[key] for key in ("id", "name", "description", "version", "created_at", "updated_at")},
            "box_count": len(active),
            "archived_box_count": len(boxes) - len(active),
            "item_count": sum(
                len(repo.find("inventory_items", box_id=box["id"], lifecycle="active")) for box in active
            ),
        }

    def detail(self, repo, row: dict, actor, include_archived: bool = False) -> dict:
        boxes = self.members(repo, row["id"])
        return {
            **self.summary(repo, row),
            "boxes": [self.catalog.summary(repo, box, actor) for box in boxes],
            "items": [
                {
                    "box_code": box["public_code"],
                    "box_name": box["name"],
                    "box_lifecycle": box["lifecycle"],
                    "item": self.catalog.item_view(item, box["public_code"]),
                }
                for box in boxes
                if include_archived or box["lifecycle"] == "active"
                for item in sorted(
                    repo.find("inventory_items", box_id=box["id"], lifecycle="active"),
                    key=lambda item: (item["normalized_name"], item["id"]),
                )
            ],
        }

    def list_collections(self, repo, query: str) -> dict:
        query = unicodedata.normalize("NFC", query.strip()).casefold()
        rows = sorted(repo.find("collections"), key=lambda row: (row["normalized_name"], row["id"]))
        return {
            "items": [
                self.summary(repo, row)
                for row in rows
                if not query or query in row["name"].casefold() or query in row["description"].casefold()
            ]
        }

    @staticmethod
    def tags(repo) -> dict:
        return {
            "items": repo.rows(
                "SELECT t.id,t.name,count(b.id) AS box_count FROM tags t "
                "LEFT JOIN box_tags bt ON bt.tag_id=t.id "
                "LEFT JOIN boxes b ON b.id=bt.box_id AND b.lifecycle='active' "
                "GROUP BY t.id ORDER BY t.normalized_name,t.id"
            )
        }

    @staticmethod
    def fields(repo, body: dict, current_id: str | None = None) -> dict:
        fields: dict[str, str] = {}
        if "name" in body:
            name, normalized = canonical_name(body["name"], 120, "Collection name")
            existing = repo.one("collections", normalized_name=normalized)
            require(
                existing is None or existing["id"] == current_id,
                "collection.name_conflict",
                "A collection already uses this name.",
            )
            fields.update(name=name, normalized_name=normalized)
        if "description" in body:
            description = unicodedata.normalize("NFC", body["description"])
            require(
                len(description) <= 2000
                and all(unicodedata.category(c) not in {"Cc", "Cs"} or c in "\n\r\t" for c in description),
                "text.invalid",
                "Collection description must be plain text up to 2000 characters.",
                422,
            )
            fields["description"] = description
        return fields

    def replace_members(self, repo, row: dict, codes: list[str]) -> set[str]:
        desired = {}
        for code in codes:
            box = self.catalog.box(repo, BoxCode.parse(code).value)
            desired[box["id"]] = box
        existing = {box["id"]: box for box in self.members(repo, row["id"])}
        changed = set(existing) ^ set(desired)
        for box_id in changed:
            Box.require_active((desired if box_id in desired else existing)[box_id])
        for box_id in set(existing) - set(desired):
            repo.delete("collection_boxes", collection_id=row["id"], box_id=box_id)
        for box_id in set(desired) - set(existing):
            repo.insert("collection_boxes", {"collection_id": row["id"], "box_id": box_id})
        return changed

    @staticmethod
    def touch_boxes(repo, ids: set[str], actor) -> None:
        for box_id in sorted(ids):
            repo.execute(
                "UPDATE boxes SET version=version+1,updated_at=:at,updated_by=:actor WHERE id=:id",
                {"at": now(), "actor": actor.user["id"], "id": box_id},
            )
            project_box(repo, box_id)

    def create(self, repo, body: dict, actor) -> dict:
        actor.authorize("editor")
        at = now()
        row = {
            "id": new_id(),
            "description": "",
            **self.fields(repo, body),
            "version": 1,
            "created_at": at,
            "updated_at": at,
        }
        repo.insert("collections", row)
        changed = self.replace_members(repo, row, body.get("box_codes", []))
        self.touch_boxes(repo, changed, actor)
        repo.audit(actor.user["id"], "collection.created", "collection", row["id"], actor.request_id)
        return row

    def update(self, repo, collection_id: str, body: dict, actor, version: str | None) -> dict:
        actor.authorize("editor")
        row = self.load(repo, collection_id)
        check_etag(version, etag("collection", row["id"], row["version"]))
        fields = self.fields(repo, body, row["id"])
        affected = (
            {box["id"] for box in self.members(repo, row["id"])}
            if fields.get("name", row["name"]) != row["name"]
            else set()
        )
        if "box_codes" in body:
            affected |= self.replace_members(repo, row, body["box_codes"])
        repo.update(
            "collections", {**fields, "version": row["version"] + 1, "updated_at": now()}, id=row["id"]
        )
        self.touch_boxes(repo, affected, actor)
        repo.audit(actor.user["id"], "collection.updated", "collection", row["id"], actor.request_id)
        return self.load(repo, row["id"])

    def delete(self, repo, collection_id: str, actor, version: str | None) -> None:
        actor.authorize("editor")
        row = self.load(repo, collection_id)
        check_etag(version, etag("collection", row["id"], row["version"]))
        affected = {box["id"] for box in self.members(repo, row["id"])}
        repo.delete("collections", id=row["id"])
        self.touch_boxes(repo, affected, actor)
        repo.audit(actor.user["id"], "collection.deleted", "collection", row["id"], actor.request_id)
