import fcntl
import json
import shutil
import threading

from boxen import __version__
from boxen.discovery.infrastructure.search import verify_search
from boxen.media.infrastructure.storage import check_space
from boxen.operations.infrastructure.migrate import CURRENT_SCHEMA_VERSION
from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, new_id, now


def backup_view(row: dict) -> dict:
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "status",
                "format_version",
                "schema_version",
                "file_count",
                "total_bytes",
                "created_at",
                "completed_at",
                "verified_at",
            )
        },
        "error": {"code": row["error_code"], "summary": row["error_summary"] or "Backup failed."}
        if row["error_code"]
        else None,
    }


def maintenance_view(row: dict) -> dict:
    return {
        **{
            k: row[k]
            for k in (
                "id",
                "kind",
                "state",
                "progress_current",
                "progress_total",
                "created_at",
                "updated_at",
                "completed_at",
            )
        },
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": {"code": row["error_code"], "summary": row["error_summary"] or "Maintenance failed."}
        if row["error_code"]
        else None,
    }


class Operations:
    def __init__(self, settings, database, vision, media, backups):
        self.settings, self.database, self.vision, self.media, self.backups = (
            settings,
            database,
            vision,
            media,
            backups,
        )

    def status(self, repo, actor) -> dict:
        at = now()
        heartbeat = repo.setting("worker_heartbeat", "")
        worker_ready = bool(heartbeat and after(60, heartbeat) > at)
        components = {
            "database": {"status": "ready", "checked_at": at},
            "worker": {
                "status": "ready" if worker_ready else "degraded",
                "message": "Worker ready."
                if worker_ready
                else "The worker is not responding. Queued work is preserved.",
                "checked_at": at,
            },
            "ai": {
                **repo.setting(
                    "ai_readiness",
                    {
                        "status": "unavailable",
                        "code": "ai.not_installed",
                        "message": "Remote AI is not configured."
                        if self.settings.ai_mode == "remote"
                        else "Local AI is not installed.",
                    },
                ),
                "checked_at": at,
            },
            "search": {
                "status": "ready"
                if repo.one("search_projection_state", singleton=1)["state"] == "ready"
                else "degraded",
                "checked_at": at,
            },
        }
        limits = {
            "max_upload_bytes": self.settings.max_upload_bytes,
            "max_image_pixels": self.settings.max_image_pixels,
            "analysis_queue_limit": 500,
            "page_limit": 100,
        }
        if actor.user["role"] == "owner":
            usage = shutil.disk_usage(self.settings.data_dir)
            free_percent = usage.free / usage.total * 100
            components["storage"] = {
                "status": "ready" if usage.free > 10 * 1024**3 and free_percent > 15 else "degraded",
                "message": f"{usage.free // 1024**3} GiB free",
                "checked_at": at,
            }
            verified = [b for b in repo.find("backups", status="verified") if b["verified_at"]]
            latest = max((b["verified_at"] for b in verified), default="")
            components["backup"] = {
                "status": "ready" if latest and after(86400, latest) > at else "degraded",
                "message": "A recent verified backup is available."
                if latest and after(86400, latest) > at
                else "Create a verified backup.",
                "checked_at": at,
            }
            limits.update(
                storage_free_bytes=usage.free,
                storage_total_bytes=usage.total,
                failed_analysis_jobs=len(repo.find("analysis_jobs", state="failed")),
                queued_analysis_jobs=len(repo.find("analysis_jobs", state="queued")),
            )
        return {
            "application_version": __version__,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "runtime_offline": self.settings.ai_mode == "local",
            "components": components,
            "limits": limits,
        }

    def request_backup(self, repo, actor) -> dict:
        actor.authorize("owner")
        check_space(self.settings)
        require(
            not any(b["status"] in {"creating", "verifying"} for b in repo.find("backups")),
            "backup.already_running",
            "A backup operation is already running.",
        )
        backup_id = new_id()
        repo.insert(
            "backups",
            {
                "id": backup_id,
                "status": "creating",
                "relative_path": "backup-" + backup_id,
                "format_version": 1,
                "schema_version": CURRENT_SCHEMA_VERSION,
                "requested_by": actor.user["id"],
                "created_at": now(),
            },
        )
        repo.audit(actor.user["id"], "backup.requested", "backup", backup_id, actor.request_id)
        return repo.one("backups", id=backup_id)

    def request_verify(self, repo, backup_id: str, actor) -> dict:
        actor.authorize("owner")
        row = repo.one("backups", id=backup_id)
        require(row is not None and row["status"] != "deleted", "backup.not_found", "Backup not found.", 404)
        require(
            not any(b["status"] in {"creating", "verifying"} for b in repo.find("backups")),
            "backup.already_running",
            "A backup operation is already running.",
        )
        repo.update(
            "backups", {"status": "verifying", "error_code": None, "error_summary": None}, id=backup_id
        )
        return repo.one("backups", id=backup_id)

    def request_maintenance(self, repo, kind: str, actor) -> dict:
        actor.authorize("owner")
        require(
            not any(j["state"] in {"queued", "running"} for j in repo.find("maintenance_jobs", kind=kind)),
            "maintenance.already_running",
            "This maintenance operation is already queued.",
        )
        job_id = new_id()
        repo.insert(
            "maintenance_jobs",
            {
                "id": job_id,
                "kind": kind,
                "operation_key": job_id,
                "state": "queued",
                "requested_by": actor.user["id"],
                "created_at": now(),
                "updated_at": now(),
            },
        )
        repo.audit(
            actor.user["id"], "maintenance.requested", "maintenance", job_id, actor.request_id, {"kind": kind}
        )
        return repo.one("maintenance_jobs", id=job_id)

    def run_once(self) -> bool:
        # Serialize selection through terminal persistence, including CLI/worker races.
        with (self.settings.data_dir / "db/operations.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return self._run_once()

    def _run_once(self) -> bool:
        with self.database.transaction() as repo:
            backup = next((b for b in repo.find("backups") if b["status"] in {"creating", "verifying"}), None)
        if backup:
            try:
                if backup["status"] == "creating":
                    values = self.backups.create(backup)
                else:
                    manifest = self.backups.verify(self.backups.path(backup))
                    values = {"file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"]}
                with self.database.transaction(write=True) as repo:
                    repo.update(
                        "backups",
                        {
                            **values,
                            "status": "verified",
                            "completed_at": now(),
                            "verified_at": now(),
                            "error_code": None,
                            "error_summary": None,
                        },
                        id=backup["id"],
                    )
                    repo.audit(backup["requested_by"], "backup.verified", "backup", backup["id"], new_id())
            except BlockingIOError:
                # Orphan reconciliation may briefly own backup.lock. Retry unchanged.
                return False
            except Exception as error:
                with self.database.transaction(write=True) as repo:
                    repo.update(
                        "backups",
                        {
                            "status": "failed",
                            "completed_at": now(),
                            "error_code": error.code if isinstance(error, DomainError) else "backup.failed",
                            "error_summary": error.detail
                            if isinstance(error, DomainError)
                            else "Backup could not complete. Check local storage and integrity.",
                        },
                        id=backup["id"],
                    )
            return True
        token = new_id()
        with self.database.transaction(write=True) as repo:
            for interrupted in repo.find("maintenance_jobs", state="running"):
                if interrupted["lease_expires_at"] <= now():
                    repo.update(
                        "maintenance_jobs",
                        {
                            "state": "queued",
                            "lease_token": None,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "updated_at": now(),
                        },
                        id=interrupted["id"],
                    )
            jobs = repo.find("maintenance_jobs", state="queued")
            if not jobs:
                return False
            job = min(jobs, key=lambda j: j["created_at"])
            repo.update(
                "maintenance_jobs",
                {
                    "state": "running",
                    "lease_token": token,
                    "lease_owner": "maintenance-worker",
                    "lease_expires_at": after(60),
                    "started_at": now(),
                    "updated_at": now(),
                },
                id=job["id"],
            )
        stop = threading.Event()

        def renew():
            while not stop.wait(10):
                with self.database.transaction(write=True) as repo:
                    current = repo.one("maintenance_jobs", id=job["id"])
                    if (
                        not current
                        or current["state"] != "running"
                        or current["lease_token"] != token
                        or current["lease_expires_at"] <= now()
                    ):
                        return
                    repo.update("maintenance_jobs", {"lease_expires_at": after(60)}, id=job["id"])
                    repo.set_setting("worker_heartbeat", now())

        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        result, maintenance_error = None, None
        try:
            with self.database.transaction(write=job["kind"] == "search_rebuild") as repo:
                result = (
                    self.media.store.verify(repo)
                    if job["kind"] == "media_verify"
                    else verify_search(repo, rebuild=job["kind"] == "search_rebuild")
                )
                # Fence the projection transaction itself, not just its status update.
                current = repo.one("maintenance_jobs", id=job["id"])
                require(
                    current
                    and current["state"] == "running"
                    and current["lease_token"] == token
                    and current["lease_expires_at"] > now(),
                    "maintenance.lease_lost",
                    "The maintenance lease expired; its changes were not committed.",
                    409,
                )
        except Exception as exc:
            maintenance_error = exc
        finally:
            stop.set()
            thread.join(timeout=2)
        with self.database.transaction(write=True) as repo:
            current = repo.one("maintenance_jobs", id=job["id"])
            if (
                not current
                or current["state"] != "running"
                or current["lease_token"] != token
                or current["lease_expires_at"] <= now()
            ):
                return True
            terminal = {"lease_token": None, "lease_owner": None, "lease_expires_at": None}
            if not maintenance_error:
                if job["kind"].startswith("search_") and result:
                    ready = job["kind"] == "search_rebuild" or result["mismatches"] == 0
                    repo.update(
                        "search_projection_state",
                        {
                            "state": "ready" if ready else "invalid",
                            "last_verified_at": now(),
                            "source_row_count": result["source_count"],
                            "projection_row_count": result["source_count"]
                            if ready
                            else result["projection_count"],
                        },
                        singleton=1,
                    )
                repo.update(
                    "maintenance_jobs",
                    {
                        "state": "succeeded",
                        **terminal,
                        "result_json": json.dumps(result),
                        "progress_current": 1,
                        "progress_total": 1,
                        "completed_at": now(),
                        "updated_at": now(),
                    },
                    id=job["id"],
                )
                repo.audit(
                    job["requested_by"],
                    "maintenance.completed",
                    "maintenance",
                    job["id"],
                    new_id(),
                    {"kind": job["kind"]},
                )
            else:
                repo.update(
                    "maintenance_jobs",
                    {
                        "state": "failed",
                        **terminal,
                        "error_code": "maintenance.failed",
                        "error_summary": "The integrity operation could not complete.",
                        "completed_at": now(),
                        "updated_at": now(),
                    },
                    id=job["id"],
                )
        return True
