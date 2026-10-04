import ipaddress
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
    password_pepper_file: Path | None = None
    oauth_providers_file: Path | None = None
    ai_base_url: str = "http://boxen-ai:8080"
    ai_mode: Literal["local", "remote"] = "local"
    ai_models_dir: Path | None = None
    ai_profile: str | None = None
    ai_api_key_file: Path | None = None
    ai_ca_file: Path | None = None
    ai_allow_insecure_http: bool = False
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

    @field_validator("ai_profile", "ai_models_dir", "ai_api_key_file", "ai_ca_file", mode="before")
    @classmethod
    def empty_ai_setting(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

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
        try:
            ai = urlsplit(self.ai_base_url)
            port = ai.port
            host = ai.hostname
        except ValueError:
            raise ValueError("AI endpoint must be a valid HTTP(S) URL with a valid port") from None
        if (
            ai.scheme not in {"http", "https"}
            or not host
            or "*" in host
            or ai.username is not None
            or ai.password is not None
            or "?" in self.ai_base_url
            or "#" in self.ai_base_url
            or "\\" in self.ai_base_url
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in self.ai_base_url)
            or ai.netloc.endswith(":")
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("AI endpoint must be an HTTP(S) root without credentials, query, or fragment")
        try:
            wildcard = ipaddress.ip_address(host).is_unspecified
        except ValueError:
            wildcard = False
        if wildcard:
            raise ValueError("AI endpoint must not use a wildcard host")
        if self.ai_mode == "local" and (self.ai_api_key_file is not None or self.ai_ca_file is not None):
            raise ValueError("BOXEN_AI_API_KEY_FILE and BOXEN_AI_CA_FILE require BOXEN_AI_MODE=remote")
        if self.ai_mode == "local" and (
            ai.scheme != "http"
            or host not in {"localhost", "127.0.0.1", "::1", "boxen-ai"}
            or ai.path not in {"", "/"}
        ):
            raise ValueError("AI endpoint must be the local loopback/private inference service")
        if self.ai_mode == "remote" and ai.scheme != "https" and not self.ai_allow_insecure_http:
            raise ValueError(
                "Remote AI requires HTTPS unless BOXEN_AI_ALLOW_INSECURE_HTTP is explicitly true"
            )
        self.ai_base_url = self.ai_base_url.rstrip("/")
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
        self.password_pepper_file = (
            self.password_pepper_file or self.data_dir / "secrets/password.pepper"
        ).resolve()
        if self.password_pepper_file == self.session_key_file:
            raise ValueError("Password pepper and session secret must use separate files")
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

    @property
    def models_dir(self) -> Path:
        return (self.ai_models_dir or self.data_dir / "models").resolve()

    def secret(self) -> bytes:
        path = self.session_key_file
        if path is None or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError("Session secret is missing or has unsafe permissions. Run boxen init.")
        value = path.read_bytes()
        if len(value) < 32:
            raise RuntimeError("Session secret must contain at least 256 bits.")
        return value

    def password_pepper(self) -> bytes:
        path = self.password_pepper_file
        if path is None or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError(
                "Password pepper is missing or has unsafe permissions. Restore the original pepper file; "
                "use boxen init only for a new or legacy installation."
            )
        value = path.read_bytes()
        if len(value) != 32:
            raise RuntimeError("Password pepper must contain exactly 256 bits.")
        return value
