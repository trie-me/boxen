import importlib.util
import json
import os
from pathlib import Path

import pytest
from test_provisioning import module as provisioner

spec = importlib.util.spec_from_file_location(
    "container_import", Path(__file__).resolve().parents[2] / "scripts/import_container_profile.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source_profile(settings, tmp_path):
    sources = []
    for name in ("model", "projector", "server", "license"):
        source = tmp_path / name
        source.write_text("Fixture only " + name)
        sources.append(source)
    return provisioner.provision(settings, "import-fixture", *sources[:3], "fixture", [sources[3]])


def test_copy_verify_permissions_no_overwrite(settings, tmp_path):
    source = source_profile(settings, tmp_path)
    models = tmp_path / "container-models"
    models.mkdir()
    imported = module.import_profile(source, models, uid=os.getuid(), gid=os.getgid())
    assert imported.name == "import-fixture"
    assert (imported / "model.gguf").read_bytes() == (source / "model.gguf").read_bytes()
    assert imported.stat().st_mode & 0o777 == 0o700
    assert (imported / "model.gguf").stat().st_mode & 0o777 == 0o600
    assert (imported / "llama-server").stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="already exists"):
        module.import_profile(source, models)


def test_bad_checksum_does_not_publish_or_change_source(settings, tmp_path):
    source = source_profile(settings, tmp_path)
    (source / "model.gguf").write_text("broken")
    models = tmp_path / "container-models"
    models.mkdir()
    with pytest.raises(ValueError, match="verification"):
        module.import_profile(source, models)
    assert list(models.iterdir()) == []
    assert (source / "model.gguf").read_text() == "broken"


def test_path_escape_rejected(settings, tmp_path):
    source = source_profile(settings, tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["model"]["path"] = str(tmp_path / "model")
    (source / "manifest.json").write_text(json.dumps(manifest))
    models = tmp_path / "container-models"
    models.mkdir()
    with pytest.raises(ValueError, match="inside"):
        module.import_profile(source, models)
    assert list(models.iterdir()) == []
