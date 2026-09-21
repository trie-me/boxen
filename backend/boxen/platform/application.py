import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from boxen.analysis.application import Analysis, job_view, observation_view, run_view
from boxen.analysis.infrastructure.vision import LocalVision
from boxen.catalog.application import Catalog
from boxen.catalog.domain import resolve_payload
from boxen.discovery.application import Pagination, search
from boxen.discovery.infrastructure.search import list_boxes
from boxen.discovery.suggestions import suggest_search
from boxen.identity.application import Identity, user_view
from boxen.identity.domain import ANONYMOUS_USER_ID
from boxen.inventory.application import Inventory
from boxen.labeling.infrastructure.pdf import PROFILES, LabelRenderer
from boxen.media.application import Media
from boxen.operations.application import Operations, backup_view, maintenance_view
from boxen.operations.infrastructure.backup import Backups
from boxen.operations.infrastructure.database import Database
from boxen.organization.application import Organization
from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, etag, now


@dataclass
class Result:
    body: object = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    cookie: str | None = None
    file: Path | None = None
    media_type: str = "application/json"


class Application:
    def __init__(self, settings, vision=None):
        self.settings = settings
        self.database = Database(settings)
        self.database.check_schema()
        self.identity = Identity(settings)
        self.catalog = Catalog()
        self.organization = Organization(self.catalog)
        self.inventory = Inventory()
        self.media = Media(settings, self.database)
        self.vision = vision or LocalVision(settings)
        self.analysis = Analysis(settings, self.database, self.vision, self.media, self.inventory)
        self.backups = Backups(settings, self.database)
        self.operations = Operations(settings, self.database, self.vision, self.media, self.backups)
        self.pagination = Pagination(settings.secret())
        self.labels = LabelRenderer(settings.assets)

    def frontend(self, path: str):
        from fastapi.responses import FileResponse, HTMLResponse

        root = self.settings.frontend_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise DomainError("resource.not_found", "Page not found.", 404)
        if target.is_file():
            return FileResponse(
                target,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "no-store"
                },
            )
        if (root / "index.html").is_file():
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<!doctype html><html lang='en'><title>Boxen</title><body><h1>Boxen</h1><p>The frontend build is not installed. Run the documented build command.</p></body></html>",
            status_code=503,
        )

    def preflight(self, operation, token, headers, request_id, write=False):
        public = operation in {"login", "createFirstOwner", "getSetupStatus", "getLiveness", "getReadiness"}
        if operation == "getSession" and self.settings.anonymous_access != "off":
            if headers.get("origin", self.settings.origin) != self.settings.origin:
                raise DomainError("auth.origin_invalid", "The request origin was not accepted.", 403)
            return None
        if write and headers.get("origin") != self.settings.origin:
            raise DomainError("auth.origin_invalid", "The request origin was not accepted.", 403)
        if public:
            return None
        with self.database.transaction() as repo:
            actor = self.identity.authenticate(repo, token, request_id, touch=False)
            session = repo.one("sessions", token_hash=actor.session_hash)
            touch = after(60, session["last_seen_at"]) < now()
            if (
                write
                and operation != "resolveBoxCode"
                and not hmac.compare_digest(headers.get("x-csrf-token", ""), self.identity.csrf(token))
            ):
                raise DomainError(
                    "auth.csrf_invalid", "Your security token expired. Refresh and try again.", 403
                )
        if touch:
            with self.database.transaction(write=True) as repo:
                actor = self.identity.authenticate(repo, token, request_id)
        return actor

    def execute(self, operation, params, body, headers, token, client, request_id, write, prepared=None):
        actor = self.preflight(operation, token, headers, request_id, write and operation != "renderBoxLabel")
        key = headers.get("idempotency-key") if write and operation != "renderBoxLabel" else None
        hash_body = {**body, "_params": params, "_if_match": headers.get("if-match")}
        if prepared:
            hash_body["_upload_sha256"] = prepared["sha256"]
        digest = hashlib.sha256(
            json.dumps(hash_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        route_key = operation + ":" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        bootstrap = operation == "getSession" and self.settings.anonymous_access != "off"
        with self.database.transaction(write=write or bootstrap) as repo:
            if actor:
                actor = self.identity.authenticate(repo, token, request_id, touch=False)
            if operation in {
                "reviewBoxObservations",
                "createCollection",
                "updateCollection",
                "deleteCollection",
                "createBox",
                "updateBox",
            }:
                # Recheck the current role before returning an idempotent replay too.
                actor.authorize("editor")
            if key and actor and actor.anonymous:
                # Shared principal, separate browser retries; also separate configured roles.
                key = hashlib.sha256(f"{actor.session_hash}:{actor.user['role']}:{key}".encode()).hexdigest()
                headers = {**headers, "idempotency-key": key}
            if key and actor:
                replay = repo.one(
                    "idempotency_records",
                    actor_user_id=actor.user["id"],
                    route_key=route_key,
                    idempotency_key=key,
                )
                if replay and replay["expires_at"] > now():
                    require(
                        replay["request_sha256"] == digest,
                        "request.idempotency_conflict",
                        "This request key was already used with different content.",
                    )
                    return Result(
                        json.loads(replay["response_body_json"]) if replay["response_body_json"] else None,
                        replay["response_status"],
                        json.loads(replay["response_headers_json"]),
                    )
                if replay:
                    repo.delete(
                        "idempotency_records",
                        actor_user_id=actor.user["id"],
                        route_key=route_key,
                        idempotency_key=key,
                    )
            result = self.dispatch(
                repo, operation, params, body, headers, token, actor, client, request_id, prepared
            )
            error = result if isinstance(result, DomainError) else None
            if not error and key and actor and result.status < 300:
                repo.insert(
                    "idempotency_records",
                    {
                        "actor_user_id": actor.user["id"],
                        "route_key": route_key,
                        "idempotency_key": key,
                        "request_sha256": digest,
                        "response_status": result.status,
                        "response_headers_json": json.dumps(result.headers),
                        "response_body_json": json.dumps(result.body) if result.body is not None else None,
                        "created_at": now(),
                        "expires_at": after(86400),
                    },
                )
        if error:
            raise error
        if operation == "createFirstOwner":
            (self.settings.data_dir / "secrets/setup-token").unlink(missing_ok=True)
        return result

    def dispatch(self, repo, op, p, body, headers, token, actor, client, request_id, prepared):
        row: Any
        version = headers.get("if-match")
        if op in {"getLiveness", "getReadiness"}:
            return Result({"status": "alive" if op == "getLiveness" else "ready"})
        if op == "getSetupStatus":
            return Result({"setup_required": not bool(self.identity.local_users(repo))})
        if op in {"login", "createFirstOwner"}:
            value = (
                self.identity.login(repo, body, client, request_id)
                if op == "login"
                else self.identity.setup(
                    repo, body, headers.get("x-boxen-setup-token", ""), client, request_id
                )
            )
            if isinstance(value, DomainError):
                return value
            session, cookie = value
            if token:
                repo.update(
                    "sessions", {"revoked_at": now()}, token_hash=hashlib.sha256(token.encode()).hexdigest()
                )
            return Result(session, 201 if op == "createFirstOwner" else 200, cookie=cookie)
        if op == "logout":
            repo.update("sessions", {"revoked_at": now()}, token_hash=actor.session_hash)
            repo.audit(actor.user["id"], "auth.logout", "user", actor.user["id"], request_id)
            return Result(status=204, cookie="")
        if op == "getSession":
            cookie = None
            if actor is None:
                try:
                    actor = self.identity.authenticate(repo, token, request_id)
                except DomainError as error:
                    if error.code != "auth.required" or self.settings.anonymous_access == "off":
                        raise
                    session, cookie = self.identity.start_anonymous_session(repo, request_id)
            if cookie is None:
                session = self.identity.session_view(repo, actor, token)
            return Result(
                session,
                headers={"ETag": etag("user", session["user"]["id"], session["user"]["version"])},
                cookie=cookie,
            )
        if op == "changeOwnPassword":
            value = self.identity.change_password(repo, body, actor, client)
            return value if isinstance(value, DomainError) else Result(value[0], cookie=value[1])
        if op in {"updateOwnProfile", "updateUser", "getUser", "createUser", "listUsers"}:
            if op != "updateOwnProfile":
                actor.authorize("owner")
            if op == "listUsers":
                return Result({"items": [user_view(u) for u in self.identity.local_users(repo)]})
            if op == "createUser":
                row = self.identity.create_user(repo, body, actor, request_id)
            elif op in {"updateOwnProfile", "updateUser"}:
                row = self.identity.update_user(
                    repo,
                    body,
                    actor.user["id"] if op == "updateOwnProfile" else p["user_id"],
                    actor,
                    version,
                    own=op == "updateOwnProfile",
                )
            else:
                row = repo.one("users", id=p["user_id"])
                require(
                    row is not None and row["id"] != ANONYMOUS_USER_ID,
                    "user.not_found",
                    "User not found.",
                    404,
                )
            return Result(
                user_view(row),
                201 if op == "createUser" else 200,
                {"ETag": etag("user", row["id"], row["version"]), "Location": "/api/v1/users/" + row["id"]},
            )
        if op == "listBoxes":
            filters = {key: str(UUID(p[key])) for key in ("tag_id", "collection_id") if p.get(key)}
            scope = f"boxes:{p['lifecycle']}:{p['sort']}:{json.dumps(filters, sort_keys=True)}"
            offset, snapshot = self.pagination.decode(p.get("cursor"), scope)
            rows = list_boxes(repo, p["lifecycle"], p["sort"], offset, p["limit"], snapshot, **filters)
            return Result(
                {
                    "items": [self.catalog.summary(repo, b, actor) for b in rows[: p["limit"]]],
                    "page": self.pagination.page(len(rows) > p["limit"], offset, p["limit"], snapshot, scope),
                }
            )
        if op == "listTags":
            return Result(self.organization.tags(repo))
        if op == "listCollections":
            return Result(self.organization.list_collections(repo, p.get("q", "")))
        if op in {"getCollection", "createCollection", "updateCollection", "deleteCollection"}:
            if op == "deleteCollection":
                self.organization.delete(repo, p["collection_id"], actor, version)
                return Result(status=204)
            row = (
                self.organization.create(repo, body, actor)
                if op == "createCollection"
                else self.organization.update(repo, p["collection_id"], body, actor, version)
                if op == "updateCollection"
                else self.organization.load(repo, p["collection_id"])
            )
            return Result(
                self.organization.detail(repo, row, actor, p.get("include_archived", False)),
                201 if op == "createCollection" else 200,
                {
                    "ETag": etag("collection", row["id"], row["version"]),
                    "Location": "/api/v1/collections/" + row["id"],
                },
            )
        if op == "createBox":
            row = self.catalog.create(repo, body, actor)
            return Result(
                self.catalog.detail(repo, row, actor),
                201,
                {
                    "ETag": etag("box", row["public_code"], row["version"]),
                    "Location": "/api/v1/boxes/" + row["public_code"],
                },
            )
        if op in {"getBox", "updateBox", "archiveBox", "restoreBox", "purgeBox"}:
            if op == "getBox":
                row = self.catalog.box(repo, p["box_code"])
            else:
                action = {
                    "updateBox": "update",
                    "archiveBox": "archive",
                    "restoreBox": "restore",
                    "purgeBox": "purge",
                }[op]
                row = self.catalog.update(repo, p["box_code"], body, actor, version, action)
            return (
                Result(status=204)
                if row is None
                else Result(
                    self.catalog.detail(repo, row, actor),
                    headers={"ETag": etag("box", row["public_code"], row["version"])},
                )
            )
        if op in {"listBoxImages", "uploadBoxImage", "reorderBoxImages"}:
            box = self.catalog.box(repo, p["box_code"])
            if op == "uploadBoxImage":
                row = self.media.attach(
                    repo, box, prepared, body.get("caption", ""), body.get("filename", "photo"), actor
                )
                return Result(
                    self.catalog.image_view(repo, row, box["public_code"]),
                    201,
                    {
                        "ETag": etag("image", row["id"], row["version"]),
                        "Location": "/api/v1/images/" + row["id"],
                    },
                )
            if op == "reorderBoxImages":
                self.media.reorder(repo, box, body["image_ids"], actor, version)
                box = self.catalog.box(repo, p["box_code"])
            images = sorted(
                repo.find("box_images", box_id=box["id"], lifecycle="ready"), key=lambda r: r["sort_order"]
            )
            return Result(
                {"items": [self.catalog.image_view(repo, i, box["public_code"]) for i in images]},
                headers={"ETag": etag("box", box["public_code"], box["version"])},
            )
        if op in {"getImage", "updateImage", "deleteImage", "getImageContent"}:
            if op == "getImageContent":
                path, content_type, digest = self.media.content(repo, p["image_id"], p["variant"], actor)
                return Result(
                    file=path,
                    media_type=content_type,
                    headers={
                        "ETag": '"' + digest + '"',
                        "Cache-Control": "private, max-age=3600",
                        "Content-Disposition": "attachment" if p["variant"] == "original" else "inline",
                    },
                )
            row = (
                self.media.load(repo, p["image_id"])
                if op == "getImage"
                else self.media.update(repo, p["image_id"], body, actor, version, delete=op == "deleteImage")
            )
            if op == "deleteImage":
                return Result(status=204)
            box = repo.one("boxes", id=row["box_id"])
            return Result(
                self.catalog.image_view(repo, row, box["public_code"]),
                headers={"ETag": etag("image", row["id"], row["version"])},
            )
        if op in {"listInventoryItems", "createInventoryItem"}:
            box = self.catalog.box(repo, p["box_code"])
            if op == "listInventoryItems":
                return Result(
                    {
                        "items": [
                            self.catalog.item_view(i, box["public_code"])
                            for i in repo.find("inventory_items", box_id=box["id"])
                            if p["include_removed"] or i["lifecycle"] == "active"
                        ]
                    }
                )
            return self.item_result(repo, self.inventory.create(repo, box, body, actor), 201)
        if op in {"getInventoryItem", "updateInventoryItem", "removeInventoryItem", "mergeInventoryItems"}:
            if op == "mergeInventoryItems":
                item = self.inventory.merge(repo, body, actor)
            elif op == "getInventoryItem":
                item = self.inventory.load(repo, p["item_id"])
            else:
                item = self.inventory.update(
                    repo,
                    p["item_id"],
                    {"lifecycle": "removed"} if op == "removeInventoryItem" else body,
                    actor,
                    version,
                )
            return Result(status=204) if op == "removeInventoryItem" else self.item_result(repo, item)
        if op == "requestImageAnalysis":
            row = self.analysis.request(repo, p["image_id"], body, actor, headers["idempotency-key"])
            return Result(job_view(repo, row), 202, {"Location": "/api/v1/jobs/" + row["id"]})
        if op == "getAnalysisJob":
            row = repo.one("analysis_jobs", id=p["job_id"])
            require(row is not None, "analysis.not_found", "Analysis job not found.", 404)
            tag = '"' + hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() + '"'
            return (
                Result(status=304, headers={"ETag": tag})
                if headers.get("if-none-match") == tag
                else Result(job_view(repo, row), headers={"ETag": tag})
            )
        if op == "getAnalysisRun":
            row = repo.one("ai_runs", id=p["run_id"])
            require(row is not None, "analysis.not_found", "Analysis run not found.", 404)
            return Result(run_view(repo, row))
        if op == "listBoxObservations":
            box = self.catalog.box(repo, p["box_code"])
            scope = f"observations:{box['id']}:{p['decision']}"
            offset, snapshot = self.pagination.decode(p.get("cursor"), scope)
            rows = sorted(
                [
                    o
                    for o in repo.find("item_observations", box_id=box["id"])
                    if o["created_at"] <= snapshot
                    and (p["decision"] == "all" or o["decision"] == p["decision"])
                ],
                key=lambda o: (o["created_at"], o["id"]),
            )
            page = rows[offset : offset + p["limit"] + 1]
            return Result(
                {
                    "items": [observation_view(o) for o in page[: p["limit"]]],
                    "page": self.pagination.page(len(page) > p["limit"], offset, p["limit"], snapshot, scope),
                }
            )
        if op == "reviewBoxObservations":
            box = self.catalog.box(repo, p["box_code"])
            value = self.analysis.review(repo, box, body, actor)
            return Result(
                {
                    "accepted": [
                        {
                            "observation": observation_view(result["observation"]),
                            "item": self.catalog.item_view(result["item"], box["public_code"]),
                        }
                        for result in value["accepted"]
                    ],
                    "rejected": [observation_view(result["observation"]) for result in value["rejected"]],
                    "added": [self.catalog.item_view(item, box["public_code"]) for item in value["added"]],
                }
            )
        if op in {"acceptObservation", "rejectObservation"}:
            value = self.analysis.decide(
                repo, p["observation_id"], body, actor, reject=op == "rejectObservation"
            )
            return (
                Result(observation_view(value["observation"]))
                if op == "rejectObservation"
                else Result(
                    {
                        "observation": observation_view(value["observation"]),
                        "item": self.catalog.item_view(value["item"], value["box"]["public_code"]),
                    }
                )
            )
        if op == "searchBoxes":
            return Result(search(repo, p, actor, self.pagination, self.catalog))
        if op == "suggestSearch":
            return Result(suggest_search(repo, p, actor))
        if op == "resolveBoxCode":
            code, kind = resolve_payload(body["input"], self.settings.origin)
            return Result(
                {
                    "input_kind": kind,
                    "canonical_payload": code.qr_payload,
                    "box": self.catalog.summary(repo, self.catalog.box(repo, code.value), actor),
                }
            )
        if op == "listLabelProfiles":
            return Result({"items": PROFILES})
        if op == "renderBoxLabel":
            actor.authorize("editor")
            self.identity.rate_limit(
                repo,
                self.identity.rate_key(actor.user["id"], "label", "label"),
                maximum=30,
                window=60,
                consume=True,
            )
            box = self.catalog.box(repo, p["box_code"])
            data, tag = self.labels.render(box, p["profile"])
            return Result(
                data,
                media_type="application/pdf",
                headers={
                    "ETag": tag,
                    "Content-Disposition": f'attachment; filename="box-{box["public_code"]}.pdf"',
                },
            )
        if op == "getSystemStatus":
            return Result(self.operations.status(repo, actor))
        if op in {"listBackups", "createBackup", "getBackup", "verifyBackup"}:
            actor.authorize("owner")
            if op == "listBackups":
                return Result(
                    {
                        "items": [
                            backup_view(b)
                            for b in sorted(repo.find("backups"), key=lambda b: b["created_at"], reverse=True)
                            if b["status"] != "deleted"
                        ]
                    }
                )
            row = (
                self.operations.request_backup(repo, actor)
                if op == "createBackup"
                else self.operations.request_verify(repo, p["backup_id"], actor)
                if op == "verifyBackup"
                else repo.one("backups", id=p["backup_id"])
            )
            require(row is not None, "backup.not_found", "Backup not found.", 404)
            return Result(
                backup_view(row),
                200 if op == "getBackup" else 202,
                {"Location": "/api/v1/backups/" + row["id"]},
            )
        if op in {"verifySearchProjection", "rebuildSearchProjection", "verifyMedia", "getMaintenanceJob"}:
            actor.authorize("owner")
            if op == "getMaintenanceJob":
                row = repo.one("maintenance_jobs", id=p["job_id"])
                require(row is not None, "maintenance.not_found", "Maintenance job not found.", 404)
            else:
                row = self.operations.request_maintenance(
                    repo,
                    {
                        "verifySearchProjection": "search_verify",
                        "rebuildSearchProjection": "search_rebuild",
                        "verifyMedia": "media_verify",
                    }[op],
                    actor,
                )
            return Result(
                maintenance_view(row),
                200 if op == "getMaintenanceJob" else 202,
                {"Location": "/api/v1/maintenance/" + row["id"]},
            )
        raise RuntimeError(f"Unimplemented operation: {op}")

    def item_result(self, repo, item, status=200):
        box = repo.one("boxes", id=item["box_id"])
        return Result(
            self.catalog.item_view(item, box["public_code"]),
            status,
            {"ETag": etag("item", item["id"], item["version"]), "Location": "/api/v1/items/" + item["id"]},
        )
