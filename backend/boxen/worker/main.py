import fcntl
import logging
import signal
import threading

from boxen.identity.domain import Actor
from boxen.platform.application import Application
from boxen.shared.values import after, new_id, now


def tick(application, worker_id, schedule=True):
    health = application.vision.readiness()
    with application.database.transaction(write=True) as repo:
        repo.set_setting("worker_heartbeat", now())
        repo.set_setting("ai_readiness", health)
        sweep_due = after(3600, repo.setting("last_media_sweep", "1970-01-01T00:00:00Z")) < now()
        if sweep_due:
            repo.set_setting("last_media_sweep", now())
        if schedule:
            owners = repo.find("users", role="owner", status="active")
            backups = repo.find("backups")
            latest = max((b["created_at"] for b in backups), default="")
            if (
                owners
                and not any(b["status"] in {"creating", "verifying"} for b in backups)
                and (not latest or after(86400, latest) < now())
            ):
                application.operations.request_backup(repo, Actor(owners[0], "worker", now(), new_id()))
    if sweep_due:
        application.media.reconcile()
    if application.operations.run_once():
        return True
    job = application.analysis.claim(worker_id)
    if not job:
        return False
    stop = threading.Event()

    def renew():
        while not stop.wait(10):
            if not application.analysis.renew(job):
                return
            with application.database.transaction(write=True) as repo:
                repo.set_setting("worker_heartbeat", now())

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        application.analysis.execute(job)
    finally:
        stop.set()
        thread.join(timeout=2)
    return True


def run(settings, once=False):
    application = Application(settings)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    worker_id = new_id()
    with (
        (settings.data_dir / "db/runtime.lock").open("a+") as runtime_lock,
        (settings.data_dir / "db/worker.lock").open("a+") as worker_lock,
    ):
        fcntl.flock(runtime_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while not stop.is_set():
            try:
                active = tick(application, worker_id)
            except Exception as error:
                logging.getLogger("boxen").error("worker_tick_failed type=%s", type(error).__name__)
                active = False
            if once:
                break
            if not active:
                stop.wait(2)
    application.database.close()
