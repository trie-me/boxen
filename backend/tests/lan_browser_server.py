"""Disposable HTTP fixture: boxen.test maps to loopback only in the test browser."""

import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from boxen.shared.errors import DomainError
from boxen.worker.main import tick
from PIL import Image
from test_ai_operations import FakeVision


class BrowserVision(FakeVision):
    """Deterministic browser-only worker; never invokes a real model/service."""

    def __init__(self, settings):
        super().__init__(settings)
        self.attempts = {}

    def readiness(self):
        return {"status": "ready", "code": None, "message": "Browser test fixture"}

    def analyze(self, path):
        # Leave a real queued/running interval for the UI and navigation tests.
        time.sleep(0.8)
        with Image.open(path) as image:
            pixel = image.convert("RGB").getpixel((0, 0))
            assert isinstance(pixel, tuple) and len(pixel) == 3
            red, green, blue = pixel
        attempt = self.attempts.get(str(path), 0) + 1
        self.attempts[str(path)] = attempt
        if red > 200 and green < 50 and blue < 50 and attempt == 1:
            raise DomainError("ai.output_truncated", "Fixture model reached its token limit.", 503)
        result = super().analyze(path)
        if green > 200 and red < 50 and blue < 50:
            result["observations"] = []
        return result


with tempfile.TemporaryDirectory(prefix="boxen-lan-e2e-") as data_dir:
    settings = Settings(
        env="development",
        origin=os.environ.get("BOXEN_TEST_ORIGIN", "http://boxen.test:8174"),
        # Exercise the default anonymous role, without changing the viewer fixture.
        data_dir=Path(data_dir),
        disk_reserve_bytes=0,
        disk_reserve_percent=0,
        frontend_dir=Path(
            os.environ.get("BOXEN_TEST_FRONTEND_DIR", Path(__file__).resolve().parents[1] / "boxen/static")
        ),
    )
    initialize(settings)
    app = create_app(settings, vision=BrowserVision(settings))
    stopped = threading.Event()

    def work():
        while not stopped.is_set():
            tick(app.state.services, "browser-fixture-worker", schedule=False)
            stopped.wait(0.1)

    worker = threading.Thread(target=work, daemon=True)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(test_app):
        async with original_lifespan(test_app):
            worker.start()
            try:
                yield
            finally:
                stopped.set()
                worker.join(timeout=5)

    app.router.lifespan_context = fixture_lifespan
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("BOXEN_TEST_PORT", "8174")),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        access_log=False,
    )
