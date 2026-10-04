import fcntl
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from boxen.catalog.domain import Box
from boxen.media.infrastructure.storage import ObjectStore, check_space, file_hash
from boxen.shared.errors import DomainError, require
from boxen.shared.values import check_etag, etag, new_id, now, text_value


class Media:
    def __init__(self, settings, database):
        self.settings = settings
        self.database = database
        self.store = ObjectStore(settings.data_dir / "media")

    def reconcile(self, grace_seconds: int = 3600) -> dict:
        """Recover interrupted uploads without exposing partial files or erasing originals.

        Orphan bytes move into a dated quarantine; no automatic permanent erasure.
        A backup lock plus a write transaction fences snapshot copying and attachment.
        """
        counts = {"staging_quarantined": 0, "objects_quarantined": 0}
        cutoff = time.time() - grace_seconds
        quarantine = self.settings.data_dir / "media/quarantine" / new_id()
        with (self.settings.data_dir / "db/backup.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return counts
            with self.database.transaction(write=True) as repo:
                references = {
                    r[key]
                    for r in repo.find("box_images")
                    for key in ("original_storage_key", "display_storage_key", "thumbnail_storage_key")
                    if r[key]
                }
                candidates = []
                for category in ("staging", "originals", "display", "thumbnails"):
                    for path in (self.store.root / category).rglob("*"):
                        key = str(path.relative_to(self.store.root))
                        if (
                            path.is_file()
                            and not path.is_symlink()
                            and path.stat().st_mtime < cutoff
                            and key not in references
                        ):
                            candidates.append((path, key, category))
                for path, key, category in candidates:
                    target = quarantine / key
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    path.replace(target)
                    counts["staging_quarantined" if category == "staging" else "objects_quarantined"] += 1
                repo.set_setting("media_reconciliation", {**counts, "checked_at": now()})
        return counts

    def stage(self, stream) -> Path:
        check_space(self.settings)
        with tempfile.NamedTemporaryFile(
            dir=self.settings.data_dir / "media/staging", suffix=".part", delete=False
        ) as target:
            path = Path(target.name)
            total = 0
            try:
                while chunk := stream.read(65536):
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise DomainError("image.too_large", "This photo exceeds the upload size limit.", 413)
                    target.write(chunk)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return path

    @staticmethod
    def clear_staging(path: Path) -> None:
        for candidate in (path, path.with_suffix(".display.webp"), path.with_suffix(".thumbnail.webp")):
            candidate.unlink(missing_ok=True)

    def prepare(self, path: Path) -> dict:
        check_space(self.settings)
        if path.stat().st_size > self.settings.max_upload_bytes:
            raise DomainError("image.too_large", "This photo exceeds the upload size limit.", 413)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "boxen.media.processor",
                    str(path),
                    str(self.settings.max_image_pixels),
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
            data = json.loads(result.stdout)
            # The full-size WebP is authoritative for new uploads. Keep the input
            # staged until the request's finally block clears it, including on errors.
            normalized = path.with_suffix(".display.webp")
            return {
                **data,
                "path": path,
                "sha256": file_hash(normalized),
                "byte_size": normalized.stat().st_size,
            }
        except (subprocess.SubprocessError, ValueError):
            raise DomainError(
                "image.invalid", "Use a valid, single-frame JPEG, PNG, or WebP photo within the image limits."
            ) from None

    def attach(self, repo, box: dict, prepared: dict, caption: str, filename: str, actor) -> dict:
        actor.authorize("editor")
        Box.require_active(box)
        text_value(caption, 500, "Caption", empty=True)
        duplicate = repo.one("box_images", box_id=box["id"], sha256=prepared["sha256"], lifecycle="ready")
        if duplicate:
            return duplicate
        image_id = new_id()
        at = now()
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename.replace("\\", "/").split("/")[-1])[:200] or "photo"
        order = (
            max(
                [r["sort_order"] for r in repo.find("box_images", box_id=box["id"], lifecycle="ready")],
                default=-1,
            )
            + 1
        )
        row = {
            "id": image_id,
            "box_id": box["id"],
            "lifecycle": "staged",
            "original_filename": filename,
            "sha256": prepared["sha256"],
            "caption": caption,
            "sort_order": order,
            "version": 1,
            "created_by": actor.user["id"],
            "created_at": at,
            "updated_at": at,
            "deleted_at": None,
        }
        repo.insert("box_images", row)
        path = prepared["path"]
        display_path = path.with_suffix(".display.webp")
        original = self.store.commit(display_path, "originals", prepared["sha256"], prepared["extension"])
        # Viewing and backup use the same normalized file, without a second full-size copy.
        thumb_path = path.with_suffix(".thumbnail.webp")
        thumbnail = self.store.commit(thumb_path, "thumbnails", file_hash(thumb_path), "webp")
        repo.update(
            "box_images",
            {
                "lifecycle": "ready",
                "original_storage_key": original,
                "display_storage_key": original,
                "thumbnail_storage_key": thumbnail,
                "media_type": prepared["media_type"],
                "byte_size": prepared["byte_size"],
                "width": prepared["width"],
                "height": prepared["height"],
                "derivative_renderer_version": "pillow-webp-v2",
            },
            id=image_id,
        )
        self.touch_box(repo, box, actor)
        repo.audit(actor.user["id"], "image.attached", "image", image_id, actor.request_id)
        return repo.one("box_images", id=image_id)

    def load(self, repo, image_id: str) -> dict:
        row = repo.one("box_images", id=image_id)
        require(row is not None and row["lifecycle"] != "deleted", "image.not_found", "Photo not found.", 404)
        return row

    def update(
        self, repo, image_id: str, body: dict, actor, version: str | None, delete: bool = False
    ) -> dict:
        actor.authorize("editor")
        row = self.load(repo, image_id)
        box = repo.one("boxes", id=row["box_id"])
        Box.require_active(box)
        check_etag(version, etag("image", image_id, row["version"]))
        changes = {"version": row["version"] + 1, "updated_at": now()}
        if delete:
            changes.update(lifecycle="deleted", deleted_at=now())
            for job in repo.find("analysis_jobs", image_id=image_id):
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
            for obs in repo.find("item_observations", image_id=image_id, decision="pending"):
                repo.update(
                    "item_observations",
                    {"decision": "superseded", "decided_at": now(), "decided_by": actor.user["id"]},
                    id=obs["id"],
                )
        else:
            changes["caption"] = text_value(body["caption"], 500, "Caption", empty=True)
        repo.update("box_images", changes, id=image_id)
        self.touch_box(repo, box, actor)
        repo.audit(
            actor.user["id"],
            "image.removed" if delete else "image.caption_changed",
            "image",
            image_id,
            actor.request_id,
        )
        return repo.one("box_images", id=image_id)

    def reorder(self, repo, box: dict, image_ids: list[str], actor, version: str | None) -> None:
        actor.authorize("editor")
        Box.require_active(box)
        check_etag(version, etag("box", box["public_code"], box["version"]))
        images = repo.find("box_images", box_id=box["id"], lifecycle="ready")
        require(
            set(image_ids) == {i["id"] for i in images},
            "image.order_invalid",
            "The new order must include each current photo exactly once.",
        )
        temporary = max((i["sort_order"] for i in images), default=0) + len(images) + 1
        for index, image in enumerate(images):
            repo.update("box_images", {"sort_order": temporary + index}, id=image["id"])
        versions = {i["id"]: i["version"] for i in images}
        for index, image_id in enumerate(image_ids):
            repo.update(
                "box_images",
                {"sort_order": index, "version": versions[image_id] + 1, "updated_at": now()},
                id=image_id,
            )
        self.touch_box(repo, box, actor)
        repo.audit(actor.user["id"], "image.reordered", "box", box["public_code"], actor.request_id)

    @staticmethod
    def touch_box(repo, box: dict, actor) -> None:
        repo.update(
            "boxes",
            {"version": box["version"] + 1, "updated_at": now(), "updated_by": actor.user["id"]},
            id=box["id"],
        )

    def content(self, repo, image_id: str, variant: str, actor) -> tuple[Path, str, str]:
        actor.authorize("editor" if variant == "original" else "viewer")
        row = self.load(repo, image_id)
        require(row["lifecycle"] == "ready", "image.not_ready", "This photo is not ready.")
        path = self.store.path(row[f"{'thumbnail' if variant == 'thumbnail' else variant}_storage_key"])
        require(
            path.is_file(),
            "image.missing",
            "This photo is missing from local storage. Ask the owner to run an integrity check.",
            503,
        )
        return path, row["media_type"] if variant == "original" else "image/webp", file_hash(path)
