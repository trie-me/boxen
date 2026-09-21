"""Start a verified, local llama.cpp CPU profile in the foreground, with no downloads."""

import argparse
import json
import os

from boxen.analysis.infrastructure.vision import LocalVision
from boxen.platform.config import Settings


def command(settings, port=8080, threads=8):
    if not 1024 <= port <= 65535 or not 1 <= threads <= 64:
        raise ValueError("Use an unprivileged port and 1–64 CPU threads.")
    vision = LocalVision(settings)
    if not vision.profile:
        raise ValueError("A checksum-verified BOXEN_AI_PROFILE is required.")
    profile = vision.profile
    root = settings.data_dir / "models" / profile["profile_id"]
    binary = root / profile["runtime"]["path"]
    if profile["runtime"]["id"] != "llama.cpp" or not os.access(binary, os.X_OK):
        raise ValueError("The selected runtime must be an executable llama.cpp server.")
    return [
        str(binary),
        "--model",
        str(root / profile["model"]["path"]),
        "--mmproj",
        str(root / profile["projector"]["path"]),
        "--alias",
        profile["model"]["id"],
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--offline",
        "--cors-origins",
        f"http://127.0.0.1:{port}",
        "--no-webui",
        "--jinja",
        "--device",
        "none",
        "--n-gpu-layers",
        "0",
        "--no-mmproj-offload",
        "--ctx-size",
        "8192",
        "--parallel",
        "1",
        "--threads",
        str(threads),
        "--threads-batch",
        str(threads),
    ]


def environment():
    # llama.cpp environment options could otherwise select remote models/RPC,
    # change the bind address, or enable unrelated services.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("LLAMA_", "HF_", "GGML_", "MTMD_"))
        and key not in {"LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH"}
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    settings = Settings.load()
    if args.profile:
        settings = Settings.model_validate({**settings.model_dump(), "ai_profile": args.profile})
    argv = command(settings, args.port, args.threads)
    if args.print_command:
        print(json.dumps(argv))
        return
    os.execve(argv[0], argv, environment())


if __name__ == "__main__":
    main()
