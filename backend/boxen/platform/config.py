import os
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env: str = "production"
    origin: str = "https://boxen.local"
    anonymous_access: Literal["off", "viewer", "editor"] = "editor"
    data_dir: Path = Path("/var/lib/boxen")
    database_path: Path | None = None
    session_key_file: Path | None = None
    ai_base_url: str = "http://boxen-ai:8080"
    ai_profile: str | None = None
    max_upload_bytes: int = 25 * 1024 * 1024
    max_image_pixels: int = 50_000_000
    worker_slots: int = 1
    log_level: str = "INFO"
    backup_retention: int = 14
    disk_reserve_bytes: int = 2 * 1024**3
    disk_reserve_percent: float = 5
    frontend_dir: Path = Path(__file__).resolve().parents[1] / "static"
    ai_timeout: int = 300

    @field_validator("env")
    @classmethod
    def valid_env(cls, value: str) -> str:
        if value not in {"production", "development", "test"}:
            raise ValueError("invalid environment")
        return value

    @model_validator(mode="after")
    def secure_configuration(self) -> "Settings":
        parsed = urlsplit(self.origin)
        if (
            parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or not parsed.hostname
            or parsed.hostname in {"0.0.0.0", "::", "*"}
            or parsed.scheme not in {"https", "http"}
        ):
            raise ValueError("BOXEN_ORIGIN must be an exact HTTP(S) origin without a path")
        # Reject malformed ports before the value reaches Host/cookie handling.
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("BOXEN_ORIGIN must use a valid port")
        if parsed.scheme != "https" and self.env == "production":
            raise ValueError("Production access requires HTTPS; trusted-LAN HTTP uses BOXEN_ENV=development")
        ai = urlsplit(self.ai_base_url)
        if (
            ai.scheme != "http"
            or ai.hostname not in {"localhost", "127.0.0.1", "::1", "boxen-ai"}
            or ai.username
            or ai.query
            or ai.fragment
            or ai.path not in {"", "/"}
        ):
            raise ValueError("AI endpoint must be the local loopback/private inference service")
        if self.ai_profile and (
            "/" in self.ai_profile or "\\" in self.ai_profile or self.ai_profile in {".", ".."}
        ):
            raise ValueError("invalid AI profile identifier")
        if self.worker_slots != 1:
            raise ValueError("v1 qualification supports one worker slot")
        if (
            not 1 <= self.max_upload_bytes <= 100 * 1024**2
            or not 1 <= self.max_image_pixels <= 100_000_000
            or not 1 <= self.ai_timeout <= 300
        ):
            raise ValueError("resource limit outside supported range")
        self.data_dir = self.data_dir.resolve()
        self.database_path = (self.database_path or self.data_dir / "db/boxen.sqlite3").resolve()
        self.session_key_file = (self.session_key_file or self.data_dir / "secrets/session.key").resolve()
        if not self.database_path.is_relative_to(self.data_dir):
            raise ValueError("database must reside under the data directory")
        if self.env == "production" and (
            self.disk_reserve_bytes < 2 * 1024**3 or self.disk_reserve_percent < 5
        ):
            raise ValueError("production disk reserve may not be lowered")
        return self

    @classmethod
    def load(cls) -> "Settings":
        values = {}
        config_file = os.environ.get("BOXEN_CONFIG_FILE")
        if config_file:
            with open(config_file, "rb") as file:
                values.update(tomllib.load(file))
        for key, value in os.environ.items():
            if key.startswith("BOXEN_") and key != "BOXEN_CONFIG_FILE":
                values[key.removeprefix("BOXEN_").lower()] = value
        return cls.model_validate(values)

    @property
    def assets(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets"

    def secret(self) -> bytes:
        path = self.session_key_file
        if path is None or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError("Session secret is missing or has unsafe permissions. Run boxen init.")
        value = path.read_bytes()
        if len(value) < 32:
            raise RuntimeError("Session secret must contain at least 256 bits.")
        return value
