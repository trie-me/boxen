import hashlib
import os
import shutil
from pathlib import Path

from boxen.shared.errors import DomainError


def file_hash(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def check_space(settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    percent = usage.free / usage.total * 100
    if usage.free < settings.disk_reserve_bytes or percent < settings.disk_reserve_percent:
        raise DomainError(
            "storage.reserve",
            "Storage is below its safety reserve. Free space before adding photos, analysis, or backups.",
            507,
        )
    return {"free_bytes": usage.free, "total_bytes": usage.total, "free_percent": percent}


class ObjectStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root or "\\" in key:
            raise DomainError("storage.invalid_key", "Invalid media reference.", 500)
        return path

    def commit(self, source: Path, kind: str, content_hash: str, extension: str) -> str:
        key = f"{kind}/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}.{extension}"
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            if file_hash(destination) != content_hash:
                raise DomainError(
                    "storage.corrupt_object",
                    "An existing stored object failed its checksum. Run integrity verification.",
                    500,
                )
            source.unlink(missing_ok=True)
            return key
        with source.open("rb") as file:
            os.fsync(file.fileno())
        os.replace(source, destination)
        destination.chmod(0o600)
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return key

    def verify(self, repo) -> dict:
        rows = [r for r in repo.find("box_images", lifecycle="ready")]
        missing = 0
        corrupt = 0
        for row in rows:
            path = self.path(row["original_storage_key"])
            if not path.is_file():
                missing += 1
            elif file_hash(path) != row["sha256"]:
                corrupt += 1
        return {"checked": len(rows), "missing_originals": missing, "corrupt_originals": corrupt}
