from boxen.catalog.domain import Box
from boxen.catalog.infrastructure.markdown import markdown_columns
from boxen.discovery.infrastructure.search import project_box
from boxen.inventory.domain import InventoryItem
from boxen.shared.errors import require
from boxen.shared.values import check_etag, etag, new_id, now, quantity_milli, quantity_text


class Inventory:
    def load(self, repo, item_id: str) -> dict:
        row = repo.one("inventory_items", id=item_id)
        require(row is not None, "item.not_found", "Inventory item not found.", 404)
        return row

    def create(self, repo, box: dict, body: dict, actor, provenance: str = "manual") -> dict:
        actor.authorize("editor")
        Box.require_active(box)
        entity = InventoryItem(**body)
        entity.validate()
        at = now()
        row = {
            "id": new_id(),
            "box_id": box["id"],
            "name": entity.name,
            "normalized_name": entity.name.casefold(),
            "quantity_milli": quantity_milli(entity.quantity),
            "unit": entity.unit,
            **markdown_columns(entity.notes_markdown, "notes"),
            "provenance": provenance,
            "lifecycle": "active",
            "version": 1,
            "created_by": actor.user["id"],
            "updated_by": actor.user["id"],
            "created_at": at,
            "updated_at": at,
            "removed_at": None,
        }
        repo.insert("inventory_items", row)
        self.changed(repo, box, actor, row["id"], "created")
        return row

    def update(self, repo, item_id: str, body: dict, actor, version: str | None) -> dict:
        actor.authorize("editor")
        row = self.load(repo, item_id)
        box = repo.one("boxes", id=row["box_id"])
        Box.require_active(box)
        check_etag(version, etag("item", item_id, row["version"]))
        require(
            row["lifecycle"] == "active" or body.get("lifecycle") == "active",
            "item.removed",
            "Restore this item before editing it.",
        )
        entity = InventoryItem(
            body.get("name", row["name"]),
            body.get("quantity", quantity_text(row["quantity_milli"])),
            body.get("unit", row["unit"]),
            body.get("notes_markdown", row["notes_markdown"]),
        )
        entity.validate()
        lifecycle = body.get("lifecycle", row["lifecycle"])
        changes = {
            "name": entity.name,
            "normalized_name": entity.name.casefold(),
            "quantity_milli": quantity_milli(entity.quantity),
            "unit": entity.unit,
            **markdown_columns(entity.notes_markdown, "notes"),
            "lifecycle": lifecycle,
            "removed_at": now() if lifecycle == "removed" else None,
            "version": row["version"] + 1,
            "updated_at": now(),
            "updated_by": actor.user["id"],
            "provenance": "mixed" if row["provenance"] == "ai" else row["provenance"],
        }
        repo.update("inventory_items", changes, id=item_id)
        self.changed(repo, box, actor, item_id, "updated")
        return repo.one("inventory_items", id=item_id)

    def merge(self, repo, body: dict, actor) -> dict:
        actor.authorize("editor")
        survivor = self.load(repo, body["survivor_id"])
        check_etag(body["survivor_etag"], etag("item", survivor["id"], survivor["version"]))
        require(
            survivor["id"] not in body["merged_item_ids"],
            "item.merge_conflict",
            "An item cannot be merged into itself.",
        )
        sources = [self.load(repo, item_id) for item_id in body["merged_item_ids"]]
        require(
            all(
                item["box_id"] == survivor["box_id"] and item["lifecycle"] == "active"
                for item in [survivor, *sources]
            ),
            "item.merge_conflict",
            "Merge only active items in the same box.",
        )
        result = body.get("result") or {}
        if len({item["unit"] for item in [survivor, *sources]}) > 1:
            require(
                "quantity" in result and "unit" in result,
                "item.merge_conflict",
                "Different units require an explicit resulting quantity and unit.",
            )
        if "quantity" not in result:
            result["quantity"] = quantity_text(InventoryItem.merged_quantity([survivor, *sources]))
        require(
            result.get("lifecycle", "active") == "active",
            "item.merge_conflict",
            "The surviving item must remain active.",
        )
        updated = self.update(repo, survivor["id"], result, actor, body["survivor_etag"])
        for source in sources:
            for observation in repo.find("item_observations", accepted_item_id=source["id"]):
                repo.update("item_observations", {"accepted_item_id": survivor["id"]}, id=observation["id"])
            repo.update(
                "inventory_items",
                {
                    "lifecycle": "removed",
                    "removed_at": now(),
                    "version": source["version"] + 1,
                    "updated_at": now(),
                    "updated_by": actor.user["id"],
                },
                id=source["id"],
            )
        if any(item["provenance"] != "manual" for item in [survivor, *sources]):
            repo.update("inventory_items", {"provenance": "mixed"}, id=survivor["id"])
            updated["provenance"] = "mixed"
        self.changed(repo, repo.one("boxes", id=survivor["box_id"]), actor, survivor["id"], "merged")
        return updated

    @staticmethod
    def changed(repo, box: dict, actor, item_id: str, action: str) -> None:
        project_box(repo, box["id"])
        repo.audit(actor.user["id"], f"inventory.{action}", "item", item_id, actor.request_id)
