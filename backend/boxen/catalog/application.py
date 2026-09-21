from boxen.catalog.domain import Box, BoxCode
from boxen.catalog.infrastructure.markdown import markdown_columns, markdown_view
from boxen.discovery.infrastructure.search import project_box
from boxen.organization.application import box_refs, set_box_organization, touch_collections
from boxen.shared.errors import require
from boxen.shared.values import after, check_etag, etag, new_id, now, quantity_text


class Catalog:
    def box(self, repo, code: str) -> dict:
        row = repo.one("boxes", public_code=BoxCode.parse(code).value)
        require(row is not None, "box.not_found", "No box uses this code.", 404)
        return row

    def summary(self, repo, box: dict, actor) -> dict:
        images = sorted(
            repo.find("box_images", box_id=box["id"], lifecycle="ready"), key=lambda i: i["sort_order"]
        )
        actions = ["box.read"]
        if actor.user["role"] in {"editor", "owner"}:
            actions += ["label.render"]
            if box["lifecycle"] == "active":
                actions += [
                    "box.edit",
                    "box.archive",
                    "image.upload",
                    "image.edit",
                    "image.remove",
                    "analysis.request",
                    "observation.review",
                    "inventory.edit",
                ]
            else:
                actions += ["box.restore"]
                if actor.user["role"] == "owner":
                    actions += ["box.purge"]
        return {
            "code": box["public_code"],
            "name": box["name"],
            "lifecycle": box["lifecycle"],
            "version": box["version"],
            **box_refs(repo, box["id"]),
            "image_count": len(images),
            "item_count": len(repo.find("inventory_items", box_id=box["id"], lifecycle="active")),
            "pending_observation_count": len(
                repo.find("item_observations", box_id=box["id"], decision="pending")
            ),
            "representative_thumbnail_url": f"/api/v1/images/{images[0]['id']}/content?variant=thumbnail"
            if images
            else None,
            "created_at": box["created_at"],
            "updated_at": box["updated_at"],
            "allowed_actions": actions,
        }

    @staticmethod
    def item_view(row: dict, code: str) -> dict:
        return {
            **{
                k: row[k]
                for k in (
                    "id",
                    "name",
                    "unit",
                    "provenance",
                    "lifecycle",
                    "version",
                    "created_at",
                    "updated_at",
                )
            },
            "box_code": code,
            "quantity": quantity_text(row["quantity_milli"]),
            "notes": markdown_view(row, "notes"),
        }

    @staticmethod
    def image_view(repo, row: dict, code: str) -> dict:
        from boxen.analysis.application import job_view

        jobs = repo.find("analysis_jobs", image_id=row["id"])
        latest = max(jobs, key=lambda j: (j["created_at"], j["id"]), default=None)
        value = {
            k: row[k]
            for k in (
                "id",
                "lifecycle",
                "caption",
                "sort_order",
                "version",
                "original_filename",
                "media_type",
                "byte_size",
                "width",
                "height",
                "sha256",
                "created_at",
                "updated_at",
            )
        }
        return {
            **value,
            "box_code": code,
            "latest_analysis": job_view(repo, latest) if latest else None,
            "thumbnail_url": f"/api/v1/images/{row['id']}/content?variant=thumbnail"
            if row["lifecycle"] == "ready"
            else None,
            "display_url": f"/api/v1/images/{row['id']}/content?variant=display"
            if row["lifecycle"] == "ready"
            else None,
        }

    def detail(self, repo, box: dict, actor) -> dict:
        return {
            **self.summary(repo, box, actor),
            "description": markdown_view(box, "description"),
            "images": [
                self.image_view(repo, i, box["public_code"])
                for i in sorted(
                    repo.find("box_images", box_id=box["id"], lifecycle="ready"),
                    key=lambda r: r["sort_order"],
                )
            ],
            "items": [
                self.item_view(i, box["public_code"])
                for i in sorted(
                    repo.find("inventory_items", box_id=box["id"], lifecycle="active"),
                    key=lambda r: r["normalized_name"],
                )
            ],
        }

    def create(self, repo, body: dict, actor) -> dict:
        actor.authorize("editor")
        entity = Box(body["name"], body.get("description_markdown", ""))
        entity.validate()
        for _ in range(20):
            code = BoxCode.generate().value
            if not repo.one("boxes", public_code=code) and not repo.one(
                "box_code_tombstones", public_code=code
            ):
                break
        else:
            raise RuntimeError("Code allocation failed")
        at = now()
        row = {
            "id": new_id(),
            "public_code": code,
            "name": entity.name,
            **markdown_columns(entity.description_markdown, "description"),
            "lifecycle": "active",
            "version": 1,
            "created_by": actor.user["id"],
            "updated_by": actor.user["id"],
            "created_at": at,
            "updated_at": at,
            "archived_at": None,
        }
        repo.insert("boxes", row)
        set_box_organization(repo, row, body)
        touch_collections(repo, [c["id"] for c in box_refs(repo, row["id"])["collections"]])
        project_box(repo, row["id"])
        repo.audit(actor.user["id"], "box.created", "box", code, actor.request_id)
        return row

    def update(
        self, repo, code: str, body: dict, actor, version: str | None, action: str = "update"
    ) -> dict | None:
        actor.authorize("owner" if action == "purge" else "editor", recent=action == "purge")
        row = self.box(repo, code)
        check_etag(version, etag("box", code, row["version"]))
        collection_ids = {c["id"] for c in box_refs(repo, row["id"])["collections"]}
        if action == "purge":
            require(
                row["lifecycle"] == "archived",
                "box.archive_required",
                "Archive this box before permanently deleting it.",
            )
            require(
                body["confirmation_code"] == code,
                "box.confirmation_invalid",
                "Type the exact printed box code.",
            )
            require(
                any(
                    b["status"] == "verified" and b["verified_at"] and after(86400, b["verified_at"]) > now()
                    for b in repo.find("backups")
                ),
                "box.backup_required",
                "Create and verify a recent backup before permanently deleting a box.",
            )
            for image in repo.find("box_images", box_id=row["id"]):
                require(
                    not repo.find("analysis_jobs", image_id=image["id"], state="running"),
                    "box.jobs_running",
                    "Wait for analysis to finish before deleting this box.",
                )
            repo.audit(actor.user["id"], "box.purged", "box", code, actor.request_id)
            repo.insert("box_code_tombstones", {"public_code": code, "purged_at": now()})
            repo.delete("boxes", id=row["id"])
            touch_collections(repo, collection_ids)
            project_box(repo, row["id"])
            return None
        changes = {"version": row["version"] + 1, "updated_at": now(), "updated_by": actor.user["id"]}
        if action in {"archive", "restore"}:
            require(
                row["lifecycle"] == ("active" if action == "archive" else "archived"),
                "box.lifecycle_conflict",
                "The box is already in the requested state.",
            )
            changes.update(
                lifecycle="archived" if action == "archive" else "active",
                archived_at=now() if action == "archive" else None,
            )
            if action == "archive":
                for image in repo.find("box_images", box_id=row["id"]):
                    for job in repo.find("analysis_jobs", image_id=image["id"]):
                        if job["state"] in {"queued", "running"}:
                            repo.update(
                                "analysis_jobs",
                                {
                                    "state": "cancelled",
                                    "lease_token": None,
                                    "lease_owner": None,
                                    "lease_expires_at": None,
                                    "updated_at": now(),
                                    "completed_at": now(),
                                },
                                id=job["id"],
                            )
        else:
            Box.require_active(row)
            entity = Box(
                body.get("name", row["name"]), body.get("description_markdown", row["description_markdown"])
            )
            entity.validate()
            changes.update(name=entity.name, **markdown_columns(entity.description_markdown, "description"))
            set_box_organization(repo, row, body)
        collection_ids.update(c["id"] for c in box_refs(repo, row["id"])["collections"])
        touch_collections(repo, collection_ids)
        repo.update("boxes", changes, id=row["id"])
        project_box(repo, row["id"])
        repo.audit(actor.user["id"], f"box.{action}", "box", code, actor.request_id)
        return repo.one("boxes", id=row["id"])
