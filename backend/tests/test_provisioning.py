import importlib.util
import json
from pathlib import Path

import pytest
from boxen.analysis.infrastructure.vision import LocalVision

spec = importlib.util.spec_from_file_location(
    "boxen_provision_profile", Path(__file__).parents[2] / "scripts/provision_profile.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_provision_pins_local_artifacts_without_claiming_quality(settings, tmp_path):
    sources = []
    for name in ["model", "projector", "runtime", "license"]:
        path = tmp_path / name
        path.write_text("Synthetic fixture: " + name)
        sources.append(path)
    root = module.provision(settings, "fixture", *sources[:3], "test-build", sources[3:])
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["qualification"] == "unqualified"
    assert (root / "llama-server").stat().st_mode & 0o777 == 0o700
    assert (root / "model.gguf").stat().st_mode & 0o777 == 0o600
    assert LocalVision(settings.model_copy(update={"ai_profile": "fixture"})).profile
    with pytest.raises(FileExistsError):
        module.provision(settings, "fixture", *sources[:3], "test-build", sources[3:])
    (root / "projector.gguf").write_text("tampered")
    assert LocalVision(settings.model_copy(update={"ai_profile": "fixture"})).error == "ai.profile_invalid"


@pytest.mark.parametrize("profile", ["../escape", "nested/path", "", "UPPER"])
def test_profile_id_cannot_escape_data_root(settings, profile):
    with pytest.raises(ValueError):
        module.provision(settings, profile, "none", "none", "none", "version", ["none"])
