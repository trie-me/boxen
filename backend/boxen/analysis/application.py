import hashlib
import json
import secrets
import time

from boxen.analysis.domain import require_lease, require_pending
from boxen.analysis.infrastructure.vision import (
    GENERATION_SCHEMA_HASH,
    PREPROCESSING_VERSION,
    PROMPT,
    PROMPT_VERSION,
)
from boxen.catalog.domain import Box
from boxen.media.infrastructure.storage import check_space, file_hash
from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, check_etag, etag, new_id, now, quantity_text


def observation_view(row: dict) -> dict:
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "run_id",
                "image_id",
                "proposed_name",
                "proposed_unit",
                "decision",
                "accepted_item_id",
                "decided_at",
                "created_at",
            )
        },
        "proposed_quantity": quantity_text(row["proposed_quantity_milli"]),
        "confidence": row["confidence_ppm"] / 1_000_000 if row["confidence_ppm"] is not None else None,
        "bounding_box": json.loads(row["bounding_box_json"]) if row["bounding_box_json"] else None,
        "attributes": json.loads(row["attributes_json"]),
    }


def job_view(repo, row: dict) -> dict:
    runs = repo.find("ai_runs", job_id=row["id"])
    runs.sort(key=lambda r: r["attempt_number"])
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "image_id",
                "state",
                "model_profile",
                "prompt_version",
                "attempt_count",
                "max_attempts",
                "created_at",
                "updated_at",
                "started_at",
                "completed_at",
            )
        },
        "run_id": runs[-1]["id"] if runs else None,
        "error": {"code": row["error_code"], "summary": row["error_summary"] or "Analysis failed."}
        if row["error_code"]
        else None,
    }


def run_view(repo, row: dict) -> dict:
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "job_id",
                "image_id",
                "image_sha256",
                "prompt_version",
                "output_schema_version",
                "status",
                "started_at",
                "completed_at",
            )
        },
        "model": {
            "id": row["model_id"],
            "sha256": row["model_sha256"],
            "projector_sha256": row["projector_sha256"],
        },
        "runtime": {"id": row["runtime_id"], "version": row["runtime_version"]},
        "metrics": {k: row[k] for k in ("duration_ms", "input_tokens", "output_tokens", "peak_memory_bytes")},
        "error": {"code": row["error_code"], "summary": row["error_summary"] or "Analysis failed."}
        if row["error_code"]
        else None,
        "observations": [observation_view(o) for o in repo.find("item_observations", run_id=row["id"])],
    }


class Analysis:
    def __init__(self, settings, database, vision, media, inventory):
        self.settings, self.database, self.vision, self.media, self.inventory = (
            settings,
            database,
            vision,
            media,
            inventory,
        )

    def request(self, repo, image_id: str, body: dict, actor, idempotency_key: str) -> dict:
        actor.authorize("editor")
        check_space(self.settings)
        image = self.media.load(repo, image_id)
        Box.require_active(repo.one("boxes", id=image["box_id"]))
        require(image["lifecycle"] == "ready", "image.not_ready", "Wait for this photo to finish processing.")
        profile = self.vision.profile
        require(
            profile is not None,
            "analysis.unavailable",
            "Local AI is not installed or its profile is invalid.",
            503,
        )
        require(
            body.get("model_profile", profile["profile_id"]) == profile["profile_id"],
            "analysis.profile_unavailable",
            "The requested model profile is not installed.",
            503,
        )
        pending = repo.find("analysis_jobs", state="queued") + repo.find("analysis_jobs", state="running")
        require(
            len(pending) < 500,
            "analysis.queue_full",
            "The analysis queue is full. Wait for current jobs to finish.",
            429,
        )
        require(
            not any(
                j["image_id"] == image_id and j["model_profile"] == profile["profile_id"] for j in pending
            ),
            "analysis.already_pending",
            "This photo already has a pending analysis.",
        )
        at = now()
        row = {
            "id": new_id(),
            "image_id": image_id,
            "operation_key": hashlib.sha256(
                (image_id + profile["profile_id"] + PROMPT_VERSION + idempotency_key).encode()
            ).hexdigest(),
            "idempotency_key": idempotency_key,
            "model_profile": profile["profile_id"],
            "prompt_version": PROMPT_VERSION,
            "output_schema_version": "1.0",
            "state": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "requested_by": actor.user["id"],
            "created_at": at,
            "updated_at": at,
        }
        repo.insert("analysis_jobs", row)
        repo.audit(actor.user["id"], "analysis.requested", "image", image_id, actor.request_id)
        return repo.one("analysis_jobs", id=row["id"])

    def decide(self, repo, observation_id: str, body: dict, actor, reject: bool = False) -> dict:
        actor.authorize("editor")
        observation = repo.one("item_observations", id=observation_id)
        require(observation is not None, "observation.not_found", "Suggestion not found.", 404)
        box = repo.one("boxes", id=observation["box_id"])
        Box.require_active(box)
        require_pending(observation)
        item = None
        if not reject:
            if body["mode"] == "create":
                item = self.inventory.create(repo, box, body["item"], actor, "ai")
            else:
                item = self.inventory.load(repo, body["item_id"])
                require(
                    item["box_id"] == box["id"] and item["lifecycle"] == "active",
                    "observation.merge_invalid",
                    "Choose an active item in the same box.",
                )
                check_etag(body["item_etag"], etag("item", item["id"], item["version"]))
                if body.get("item_patch"):
                    require(
                        body["item_patch"].get("lifecycle", "active") == "active",
                        "observation.merge_invalid",
                        "The accepted item must remain active.",
                    )
                    item = self.inventory.update(
                        repo, item["id"], body["item_patch"], actor, body["item_etag"]
                    )
                if item["provenance"] == "manual":
                    repo.update(
                        "inventory_items",
                        {"provenance": "mixed", "version": item["version"] + 1, "updated_at": now()},
                        id=item["id"],
                    )
                    item = repo.one("inventory_items", id=item["id"])
        repo.update(
            "item_observations",
            {
                "decision": "rejected" if reject else "accepted",
                "accepted_item_id": item["id"] if item else None,
                "decided_by": actor.user["id"],
                "decided_at": now(),
            },
            id=observation_id,
        )
        repo.audit(
            actor.user["id"],
            "observation.rejected" if reject else "observation.accepted",
            "observation",
            observation_id,
            actor.request_id,
            {"reason": body.get("reason")} if reject else {},
        )
        return {"observation": repo.one("item_observations", id=observation_id), "item": item, "box": box}

    def review(self, repo, box: dict, body: dict, actor) -> dict:
        """Apply an explicit review set inside the caller's write transaction."""
        actor.authorize("editor")
        Box.require_active(box)
        observation_ids = [entry["observation_id"] for entry in body["accept"]] + body["reject"]
        require(
            1 <= len(observation_ids) + len(body["add"]) <= 500,
            "request.validation",
            "Submit between 1 and 500 review actions at a time.",
            422,
        )
        require(
            len(set(observation_ids)) == len(observation_ids),
            "observation.review_duplicate",
            "Each suggestion can appear only once in a review.",
            422,
        )
        for observation_id in observation_ids:
            observation = repo.one("item_observations", id=observation_id)
            require(observation is not None, "observation.not_found", "Suggestion not found.", 404)
            require(
                observation["box_id"] == box["id"],
                "observation.box_mismatch",
                "Review only suggestions from this box.",
            )
            require_pending(observation)

        # Every supplied ETag must match the initial transaction snapshot, including
        # repeated links to the same item. Never replace a stale client ETag first.
        for entry in body["accept"]:
            decision = entry["decision"]
            if decision["mode"] == "merge":
                item = self.inventory.load(repo, decision["item_id"])
                require(
                    item["box_id"] == box["id"] and item["lifecycle"] == "active",
                    "observation.merge_invalid",
                    "Choose an active item in the same box.",
                )
                check_etag(decision["item_etag"], etag("item", item["id"], item["version"]))

        accepted = []
        for entry in body["accept"]:
            decision = entry["decision"]
            if decision["mode"] == "merge":
                item = self.inventory.load(repo, decision["item_id"])
                decision = {**decision, "item_etag": etag("item", item["id"], item["version"])}
            accepted.append(self.decide(repo, entry["observation_id"], decision, actor))
        rejected = [self.decide(repo, identifier, {}, actor, reject=True) for identifier in body["reject"]]
        added = [self.inventory.create(repo, box, item, actor) for item in body["add"]]
        # Repeated links can patch an item more than once. Return its final committed
        # representation for every acceptance so no response contains an obsolete version.
        for result in accepted:
            result["item"] = self.inventory.load(repo, result["item"]["id"])
        return {"accepted": accepted, "rejected": rejected, "added": added}

    def claim(self, worker_id: str) -> dict | None:
        with self.database.transaction(write=True) as repo:
            for job in repo.find("analysis_jobs", state="running"):
                if job["lease_expires_at"] <= now():
                    failed = job["attempt_count"] >= job["max_attempts"]
                    repo.update(
                        "analysis_jobs",
                        {
                            "state": "failed" if failed else "queued",
                            "lease_token": None,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "completed_at": now() if failed else None,
                            "updated_at": now(),
                            "error_code": "ai.worker_interrupted",
                            "error_summary": "The previous worker stopped before completion.",
                        },
                        id=job["id"],
                    )
            for job in sorted(repo.find("analysis_jobs", state="queued"), key=lambda j: j["created_at"]):
                if repo.setting("retry:" + job["id"], "") > now():
                    continue
                token = secrets.token_urlsafe(24)
                repo.update(
                    "analysis_jobs",
                    {
                        "state": "running",
                        "lease_token": token,
                        "lease_owner": worker_id,
                        "lease_expires_at": after(60),
                        "attempt_count": job["attempt_count"] + 1,
                        "started_at": now(),
                        "updated_at": now(),
                        "error_code": None,
                        "error_summary": None,
                    },
                    id=job["id"],
                )
                return repo.one("analysis_jobs", id=job["id"])
        return None

    def renew(self, job: dict) -> bool:
        with self.database.transaction(write=True) as repo:
            current = repo.one("analysis_jobs", id=job["id"])
            try:
                require_lease(current, job["lease_token"])
            except DomainError:
                return False
            repo.update("analysis_jobs", {"lease_expires_at": after(60)}, id=job["id"])
            return True

    def execute(self, job: dict) -> None:
        started = time.monotonic()
        self.vision.last_metrics = {}
        self.vision.last_input_sha256 = None
        output, error = None, None
        image, display_digest = None, None
        try:
            with self.database.transaction() as repo:
                image = self.media.load(repo, job["image_id"])
            require(
                file_hash(self.media.store.path(image["original_storage_key"])) == image["sha256"],
                "ai.input_invalid",
                "The photo failed its integrity check.",
            )
            if not self.vision.profile or self.vision.profile["profile_id"] != job["model_profile"]:
                raise DomainError("ai.profile_invalid", "The requested local model profile is unavailable.")
            if job["prompt_version"] != PROMPT_VERSION:
                raise DomainError(
                    "ai.profile_changed", "The analysis profile changed. Analyze this photo again."
                )
            display_path = self.media.store.path(image["display_storage_key"])
            display_digest = file_hash(display_path)
            output = self.vision.analyze(display_path)
            output = self.vision.validate(json.dumps(output).encode())
        except DomainError as exc:
            error = exc
        except Exception:
            error = DomainError("ai.input_invalid", "The photo could not be read or analyzed.")
        if error:
            output = None
        with self.database.transaction(write=True) as repo:
            current = repo.one("analysis_jobs", id=job["id"])
            if not current:
                return
            try:
                require_lease(current, job["lease_token"])
            except DomainError:
                return
            profile = self.vision.profile
            metrics = getattr(self.vision, "last_metrics", {})
            if profile and image:
                run_id = new_id()
                repo.insert(
                    "ai_runs",
                    {
                        "id": run_id,
                        "job_id": job["id"],
                        "attempt_number": job["attempt_count"],
                        "image_id": image["id"],
                        "image_sha256": image["sha256"],
                        "model_id": profile["model"]["id"],
                        "model_sha256": profile["model"]["sha256"],
                        "projector_sha256": profile["projector"]["sha256"],
                        "runtime_id": profile["runtime"]["id"],
                        "runtime_version": profile["runtime"]["version"],
                        "prompt_version": job["prompt_version"],
                        "output_schema_version": "1.0",
                        "status": "failed" if error else "succeeded",
                        "raw_output_json": json.dumps(output) if output is not None else None,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "input_tokens": metrics.get("input_tokens"),
                        "output_tokens": metrics.get("output_tokens"),
                        "error_code": error.code if error else None,
                        "error_summary": error.detail if error else None,
                        "started_at": job["started_at"],
                        "completed_at": now(),
                    },
                )
                repo.set_setting(
                    "run-provenance:" + run_id,
                    {
                        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
                        "schema_sha256": self.vision.schema_hash,
                        "generation_schema_sha256": GENERATION_SCHEMA_HASH,
                        "preprocessing_version": PREPROCESSING_VERSION,
                        "display_sha256": display_digest,
                        "inference_input_sha256": getattr(self.vision, "last_input_sha256", None),
                        "max_image_edge": profile.get("max_image_edge"),
                        "runtime_sha256": profile["runtime"]["sha256"],
                        "parameters": {k: profile[k] for k in ("temperature", "seed", "max_output_tokens")},
                        "inference_requests": metrics.get("requests", []),
                    },
                )
                if output:
                    for index, obs in enumerate(output["observations"]):
                        repo.insert(
                            "item_observations",
                            {
                                "id": new_id(),
                                "run_id": run_id,
                                "box_id": image["box_id"],
                                "image_id": image["id"],
                                "ordinal": index,
                                "proposed_name": obs["name"].strip(),
                                "normalized_name": obs["name"].strip().casefold(),
                                "proposed_quantity_milli": obs["quantity"] * 1000
                                if obs["quantity"]
                                else None,
                                "proposed_unit": obs["unit"],
                                "confidence_ppm": round(obs["confidence"] * 1_000_000),
                                "bounding_box_json": json.dumps(obs["bounding_box"])
                                if obs["bounding_box"]
                                else None,
                                "attributes_json": json.dumps(
                                    {**obs["attributes"], "evidence": obs["evidence"]}
                                ),
                                "decision": "pending",
                                "created_at": now(),
                            },
                        )
            retryable = (
                error
                and error.code in {"ai.runtime_unavailable", "ai.timeout", "ai.output_invalid"}
                and job["attempt_count"]
                < (2 if error.code in {"ai.timeout", "ai.output_invalid"} else job["max_attempts"])
            )
            state = "queued" if retryable else "failed" if error else "succeeded"
            if retryable:
                repo.set_setting("retry:" + job["id"], after(5 if job["attempt_count"] == 1 else 30))
            repo.update(
                "analysis_jobs",
                {
                    "state": state,
                    "lease_token": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "error_code": error.code if error else None,
                    "error_summary": error.detail if error else None,
                    "updated_at": now(),
                    "completed_at": None if retryable else now(),
                },
                id=job["id"],
            )
