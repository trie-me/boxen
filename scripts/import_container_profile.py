"""Import an already provisioned profile into a dedicated container model volume.

No downloads or overwrites. Run this one-off helper as container root with the
source mounted read-only at /source and the dedicated model volume at /models.
Only the new destination is assigned to the normal runtime UID/GID 10001.
"""

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from boxen.analysis.infrastructure.vision import LocalVision
from boxen.platform.config import Settings


def import_profile(source: Path, models: Path, *, uid=10001, gid=10001) -> Path:
    source = source.resolve(strict=True)
    models = models.resolve(strict=True)
    manifest_path = source / "manifest.json"
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Profile manifest is too large.")
    manifest = json.loads(manifest_path.read_text())
    profile_id = manifest["profile_id"]
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", profile_id):
        raise ValueError("Invalid profile identifier.")
    destination = models / profile_id
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination profile already exists; no files were overwritten.")
    names = {"manifest.json", *manifest["license_files"]}
    names.update(manifest[key]["path"] for key in ("model", "projector", "runtime"))
    names.update(item["path"] for item in manifest.get("runtime_files", []))
    sources = []
    for name in names:
        path = (source / name).resolve(strict=True)
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_relative_to(source)
            or not path.is_file()
        ):
            raise ValueError("Profile artifact must be a regular file inside the source directory.")
        sources.append((relative, path))
    # A failed import removes only the newly created staging directory, never a
    # pre-existing profile or source artifact. Rename publishes only verified data.
    with tempfile.TemporaryDirectory(prefix=".import-", dir=models) as staging:
        root = Path(staging) / profile_id
        root.mkdir(mode=0o700)
        for relative, path in sources:
            target = root / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o700 if str(relative) == manifest["runtime"]["path"] else 0o600)
        settings = Settings(ai_models_dir=Path(staging), ai_profile=profile_id)
        vision = LocalVision(settings)
        if not vision.profile:
            raise ValueError("Copied profile failed checksum/prompt/schema verification.")
        for path in [*root.rglob("*"), root]:
            if path.is_dir():
                path.chmod(0o700)
            os.chown(path, uid, gid)
        # Recheck after potentially slow copying; never replace an existing tree.
        if destination.exists() or destination.is_symlink():
            raise ValueError("Destination appeared during import; refusing to replace it.")
        root.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.parent.resolve() != Path("/models") or os.geteuid() != 0:
        parser.error("Run as container root with destination /models/PROFILE in a dedicated model volume.")
    manifest = json.loads((args.source / "manifest.json").read_text())
    if args.destination.name != manifest["profile_id"]:
        parser.error("Destination name must match the manifest profile_id.")
    imported = import_profile(args.source, args.destination.parent)
    print(json.dumps({"profile": imported.name, "integrity": "verified", "owner": "10001:10001"}))


if __name__ == "__main__":
    main()
