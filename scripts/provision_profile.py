"""Copy explicitly selected local artifacts into a checksum-pinned Boxen profile.

No network/download/update behavior. This records identity, not model quality approval.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from boxen.analysis.infrastructure.vision import PROMPT, PROMPT_VERSION, LocalVision
from boxen.media.infrastructure.storage import file_hash
from boxen.platform.config import Settings


def provision(
    settings,
    profile_id,
    model,
    projector,
    runtime,
    runtime_version,
    licenses,
    display_name=None,
    runtime_libraries=(),
    max_image_edge=768,
    max_output_tokens=4096,
):
    if settings.ai_mode != "local":
        raise ValueError("Provision local artifacts with BOXEN_AI_MODE=local.")
    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", profile_id):
        raise ValueError("Use a lower-case profile ID with letters, digits, dot, underscore, or hyphen.")
    if not licenses:
        raise ValueError("At least one local license file is required.")
    if not 256 <= max_image_edge <= 2048 or not 256 <= max_output_tokens <= 8192:
        raise ValueError("Image/token limits are outside the supported range.")
    sources = [Path(path).resolve(strict=True) for path in (model, projector, runtime, *licenses)]
    if not all(path.is_file() for path in sources):
        raise ValueError("Every artifact must be a local regular file.")
    libraries: list[tuple[str, Path]] = []
    for value in runtime_libraries:
        path = Path(value)
        if not re.fullmatch(r"lib[\w.+-]+\.(?:so(?:\.[0-9]+)*|dylib)", path.name):
            raise ValueError("Runtime libraries must be named lib*.so[.version] or lib*.dylib.")
        source = path.resolve(strict=True)
        if not source.is_file() or path.name in {name for name, _ in libraries}:
            raise ValueError("Runtime library paths must be files with unique names.")
        libraries.append((path.name, source))
    os.umask(0o077)
    root = settings.models_dir / profile_id
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    identities = {}
    for kind, source, name in zip(
        ("model", "projector", "runtime"), sources[:3], ("model.gguf", "projector.gguf", "llama-server")
    ):
        target = root / name
        shutil.copy2(source, target)
        target.chmod(0o700 if kind == "runtime" else 0o600)
        identities[kind] = {
            "id": profile_id
            if kind == "model"
            else "llama.cpp"
            if kind == "runtime"
            else profile_id + "-projector",
            "path": name,
            "sha256": file_hash(target),
        }
    identities["runtime"]["version"] = runtime_version
    runtime_files = []
    for name, source in libraries:
        target = root / name
        shutil.copyfile(source, target)
        target.chmod(0o600)
        runtime_files.append({"path": name, "sha256": file_hash(target)})
    license_files = []
    for index, source in enumerate(sources[3:]):
        target = root / f"license-{index + 1}.txt"
        shutil.copyfile(source, target)
        license_files.append(target.name)
    manifest = {
        "profile_id": profile_id,
        "profile_version": 1,
        "display_name": display_name or profile_id,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": "1.0",
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "output_schema_sha256": file_hash(settings.assets / "ai-inventory-output.schema.json"),
        "license_files": license_files,
        "worker_slots": 1,
        "max_output_tokens": max_output_tokens,
        "initial_output_tokens": min(2048, max_output_tokens),
        "max_image_edge": max_image_edge,
        "temperature": 0,
        "seed": 0,
        "qualification": "unqualified",
        "runtime_files": runtime_files,
        **identities,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verified = LocalVision(settings.model_copy(update={"ai_profile": profile_id}))
    if not verified.profile:
        raise ValueError("Profile verification failed. Artifacts were retained for inspection.")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["profile", "model", "projector", "runtime", "runtime-version"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--license", action="append", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--runtime-library", action="extend", nargs="+", default=[])
    parser.add_argument("--max-image-edge", type=int, default=768)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    args = parser.parse_args()
    root = provision(
        Settings.load(),
        args.profile,
        args.model,
        args.projector,
        args.runtime,
        args.runtime_version,
        args.license,
        args.display_name,
        args.runtime_library,
        args.max_image_edge,
        args.max_output_tokens,
    )
    print(
        json.dumps(
            {
                "profile": args.profile,
                "path": str(root),
                "integrity": "verified",
                "quality": "not evaluated",
                "next": "Set BOXEN_AI_PROFILE and BOXEN_AI_BASE_URL=http://127.0.0.1:8080 in web and worker; start .venv/bin/python -m boxen.analysis.infrastructure.runtime --profile "
                + args.profile
                + ". Verify real recognition and review acceptance before relying on suggestions.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
