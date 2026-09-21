import argparse
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

from boxen.operations.infrastructure.database import initialize
from boxen.platform.application import Application
from boxen.platform.config import Settings
from boxen.shared.errors import DomainError


def web_settings(settings: Settings, host: str, port: int, origin: str | None = None) -> Settings:
    """Choose one exact browser origin, never a wildcard Host/Origin allowlist."""
    if not 1 <= port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    configured = urlsplit(settings.origin)
    if origin is None and settings.env != "production":
        if "origin" not in settings.model_fields_set or (
            configured.scheme == "http"
            and configured.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
        ):
            if host in {"0.0.0.0", "::"}:
                raise ValueError(
                    "A wildcard bind needs a browser address: add --origin http://YOUR-LAN-IP:"
                    f"{port}, or bind directly with --host YOUR-LAN-IP."
                )
            browser_host = f"[{host}]" if ":" in host else host
            origin = f"http://{browser_host}:{port}"
    return Settings.model_validate({**settings.model_dump(), "origin": origin or settings.origin})


@contextmanager
def administrative_application(settings, command, action=None):
    """Keep maintenance from crossing an offline restore's directory swap."""
    with (settings.data_dir / "db/runtime.lock").open("a+") as lock:
        # Restore owns its exclusive lock internally. Its preflight is read-only.
        if command != "restore" or action == "verify":
            mode = fcntl.LOCK_EX if command == "repair-derivatives" else fcntl.LOCK_SH
            try:
                fcntl.flock(lock, mode | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DomainError(
                    "maintenance.services_running",
                    "Another service is using this data directory. Stop services before repair or restore.",
                    409,
                ) from None
        application = Application(settings)
        try:
            yield application
        finally:
            application.database.close()


def main():
    parser = argparse.ArgumentParser(description="Boxen local inventory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize the local data directory and print the one-time setup token")
    web = sub.add_parser("web", help="Run the web/API service")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--origin", help="Exact browser URL, e.g. http://192.0.2.10:8000")
    worker = sub.add_parser("worker", help="Run the local worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("verify", help="Verify database, search, and originals")
    sub.add_parser("repair-derivatives", help="Rebuild image derivatives from originals")
    sub.add_parser("backup", help="Create a verified backup")
    restore = sub.add_parser("restore", help="Restore offline, retaining current data in quarantine")
    restore.add_argument("action", choices=["preflight", "apply", "verify"])
    restore.add_argument("backup_path", type=Path, nargs="?")
    restore.add_argument("--confirm-installation")
    args = parser.parse_args()
    settings = Settings.load()
    os.umask(0o077)
    if args.command == "init":
        token = initialize(settings)
        print(
            "Boxen initialized. One-time setup token: " + token
            if token
            else "Boxen is already initialized. Setup state was preserved."
        )
    elif args.command == "web":
        from boxen.api.app import create_app

        try:
            settings = web_settings(settings, args.host, args.port, args.origin)
        except ValueError as error:
            parser.error(str(error))
        print(f"Boxen URL: {settings.origin}", flush=True)
        print(f"Data directory: {settings.data_dir}", flush=True)
        print(f"Anonymous access: {settings.anonymous_access}", flush=True)
        if settings.anonymous_access == "editor":
            print(
                "Devices that can reach Boxen can create and edit inventory. Administration still requires an owner.",
                flush=True,
            )
        if urlsplit(settings.origin).scheme == "http" and args.host not in {"127.0.0.1", "::1", "localhost"}:
            print(
                "Trusted-LAN HTTP: traffic is not encrypted. Do not expose this port to the internet. "
                "Live browser camera requires HTTPS; QR image upload and typed codes work on HTTP.",
                flush=True,
            )
        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
            access_log=False,
        )
    elif args.command == "worker":
        from boxen.worker.main import run

        run(settings, args.once)
    else:
        with administrative_application(settings, args.command, getattr(args, "action", None)) as application:
            run_administrative_command(application, args, parser)


def run_administrative_command(application, args, parser):
    from boxen.discovery.infrastructure.search import verify_search
    from boxen.identity.domain import Actor
    from boxen.shared.values import new_id, now

    if args.command == "verify" or (args.command == "restore" and args.action == "verify"):
        with application.database.transaction() as repo:
            result = {
                "database": repo.execute("PRAGMA integrity_check").scalar(),
                "foreign_keys": repo.rows("PRAGMA foreign_key_check"),
                "search": verify_search(repo),
                "media": application.media.store.verify(repo),
            }
        print(json.dumps(result, indent=2))
        if (
            result["database"] != "ok"
            or result["foreign_keys"]
            or result["search"]["mismatches"]
            or result["media"]["missing_originals"]
            or result["media"]["corrupt_originals"]
        ):
            raise SystemExit(1)
    elif args.command == "repair-derivatives":
        with application.database.transaction() as repo:
            images = repo.find("box_images", lifecycle="ready")
        for image in images:
            with application.media.store.path(image["original_storage_key"]).open("rb") as source:
                staged = application.media.stage(source)
            try:
                application.media.prepare(staged)
                from boxen.media.infrastructure.storage import file_hash

                changes = {}
                for variant, kind in (("display", "display"), ("thumbnail", "thumbnails")):
                    path = staged.with_suffix(f".{variant}.webp")
                    changes[variant + "_storage_key"] = application.media.store.commit(
                        path, kind, file_hash(path), "webp"
                    )
                with application.database.transaction(write=True) as repo:
                    repo.update("box_images", changes, id=image["id"])
            finally:
                application.media.clear_staging(staged)
        print(json.dumps({"rebuilt": len(images)}))
    elif args.command == "backup":
        with application.database.transaction(write=True) as repo:
            owners = repo.find("users", role="owner", status="active")
            if not owners:
                parser.error("Complete owner setup before backing up.")
            row = application.operations.request_backup(repo, Actor(owners[0], "cli", now(), new_id()))
        application.operations.run_once()
        with application.database.transaction() as repo:
            print(json.dumps({"backup_id": row["id"], "status": repo.one("backups", id=row["id"])["status"]}))
    elif args.command == "restore":
        if not args.backup_path or not args.confirm_installation:
            parser.error("Restore requires a backup path and --confirm-installation.")
        print(
            json.dumps(
                application.backups.restore(
                    args.backup_path.resolve(), args.confirm_installation, args.action == "apply"
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
