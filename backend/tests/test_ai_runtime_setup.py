import json

import pytest
from boxen.analysis.infrastructure.runtime import command, environment
from boxen.analysis.infrastructure.vision import LocalVision
from test_provisioning import module


def test_local_runtime_libraries_are_copied_and_verified(settings, tmp_path):
    sources = []
    for name in ["model", "projector", "llama-server", "LICENSE", "libllama.so.0"]:
        path = tmp_path / name
        path.write_text("Fixture only: " + name)
        sources.append(path)
    # Preserve the loader's requested library name even when the source is a symlink.
    alias = tmp_path / "libllama.so"
    alias.symlink_to(sources[-1].name)
    root = module.provision(
        settings, "local-cpu", *sources[:3], "b10977", [sources[3]], runtime_libraries=[sources[-1], alias]
    )
    configured = settings.model_copy(update={"ai_profile": "local-cpu"})
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["runtime_files"]) == 2
    argv = command(configured, port=18080, threads=4)
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--alias") + 1] == "local-cpu"
    assert "--offline" in argv and "--no-mmproj-offload" in argv
    assert "--hf-repo" not in argv
    (root / "libllama.so").write_text("corruption")
    assert LocalVision(configured).error == "ai.profile_invalid"
    with pytest.raises(ValueError, match="checksum"):
        command(configured)


def test_runtime_does_not_inherit_network_or_loader_overrides(monkeypatch):
    for key in ["LLAMA_ARG_HOST", "LLAMA_ARG_HF_REPO", "LLAMA_ARG_RPC", "HF_TOKEN", "LD_PRELOAD"]:
        monkeypatch.setenv(key, "fixture")
    env = environment()
    assert not any(key.startswith(("LLAMA_", "HF_", "GGML_")) for key in env)
    assert "LD_PRELOAD" not in env


def test_runtime_uses_separate_models_directory_and_explicit_container_host(settings, tmp_path):
    settings.ai_models_dir = tmp_path / "separate-models"
    sources = []
    for name in ("model", "projector", "runtime", "license"):
        path = tmp_path / name
        path.write_text("Synthetic fixture: " + name)
        sources.append(path)
    root = module.provision(settings, "separate", *sources[:3], "test", sources[3:])
    assert root == settings.models_dir / "separate"
    assert not (settings.data_dir / "models").exists()
    settings.ai_profile = "separate"
    argv = command(settings, host="0.0.0.0")
    assert argv[argv.index("--host") + 1] == "0.0.0.0"
    assert argv[0] == str(root / "llama-server")
    assert argv[argv.index("--model") + 1] == str(root / "model.gguf")
    assert "--offline" in argv
    for host in ("192.168.1.5", "::", "localhost", "*"):
        with pytest.raises(ValueError, match="loopback"):
            command(settings, host=host)
    (root / "projector.gguf").write_text("corruption")
    with pytest.raises(ValueError, match="checksum"):
        command(settings, host="0.0.0.0")
