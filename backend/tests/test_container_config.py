"""Offline packaging contracts: parse source only, never build or start containers."""

import re
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def compose(name="compose.yaml"):
    return yaml.safe_load((DEPLOY / name).read_text())


def volumes(service):
    result = {}
    for mount in service.get("volumes", []):
        if isinstance(mount, str):
            source, target, *flags = mount.split(":")
            mount = {"source": source, "target": target, "read_only": "ro" in flags}
        result[mount["target"]] = mount
    return result


def defaults(value):
    """Resolve only the simple default expressions used in these assertions."""
    return re.sub(r"\$\{[A-Z_]+:-([^}]+)\}", r"\1", value)


def test_base_runs_images_without_checkout_or_ai():
    base = compose()
    assert set(base["services"]) == {"init", "web", "worker", "caddy"}
    for service in base["services"].values():
        assert "build" not in service
        assert "env_file" not in service
        assert not service.get("secrets")
        assert not service.get("configs")
        assert "/models" not in volumes(service)
        assert not any(key.startswith("BOXEN_AI_") for key in service["environment"])
        assert all(mount["source"] in base["volumes"] for mount in volumes(service).values())


@pytest.mark.parametrize("name", ["init", "web", "worker"])
def test_shared_app_image_and_restore_parent_volume(name):
    service = compose()["services"][name]
    assert service["image"] == "${BOXEN_IMAGE:-boxen:0.1.0}"
    assert volumes(service) == {
        "/var/lib/boxen": {"type": "volume", "source": "boxen-data", "target": "/var/lib/boxen"}
    }
    assert service["environment"]["BOXEN_DATA_DIR"] == "/var/lib/boxen/data"


def test_initialization_is_explicit_and_token_is_not_logged():
    services = compose()["services"]
    assert services["init"]["profiles"] == ["tools"]
    assert services["init"]["command"] == ["init"]
    assert services["init"]["restart"] == "no"
    assert services["init"]["logging"] == {"driver": "none"}
    assert services["web"]["command"] == ["web", "--host", "0.0.0.0"]
    assert services["worker"]["command"] == ["worker"]
    for name in ("web", "worker", "caddy"):
        assert "init" not in services[name].get("depends_on", {})
    assert 'ENTRYPOINT ["boxen"]' in (ROOT / "Dockerfile").read_text()
    assert '"init"' not in (ROOT / "Dockerfile").read_text()


@pytest.mark.parametrize("name", ["init", "web", "worker", "caddy", "boxen-ai"])
def test_routine_services_are_nonroot_with_readonly_roots(name):
    filename = "compose.ai-local.yaml" if name == "boxen-ai" else "compose.yaml"
    service = compose(filename)["services"][name]
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert not service.get("privileged")
    assert not service.get("cap_add")
    assert not service.get("network_mode")
    assert not service.get("devices")
    assert service["tmpfs"] and all("noexec,nosuid" in mount for mount in service["tmpfs"])


def test_base_is_private_with_only_loopback_tls_published():
    base = compose()
    assert base["networks"] == {"private": {"internal": True}, "ingress": {}}
    for name in ("init", "web", "worker"):
        assert base["services"][name]["networks"] == ["private"]
        assert not base["services"][name].get("ports")
    proxy = base["services"]["caddy"]
    assert set(proxy["networks"]) == {"private", "ingress"}
    assert proxy["ports"] == [
        {
            "target": 8443,
            "published": "${BOXEN_HTTPS_PORT:-8443}",
            "host_ip": "${BOXEN_BIND_ADDRESS:-127.0.0.1}",
            "protocol": "tcp",
        }
    ]


def test_tls_host_and_app_origin_use_the_same_public_host_and_port():
    services = compose()["services"]
    proxy = services["caddy"]
    host = proxy["environment"]["BOXEN_HOST"]
    port = proxy["ports"][0]["published"]
    for name in ("init", "web", "worker"):
        origin = services[name]["environment"]["BOXEN_ORIGIN"]
        assert origin == f"https://{host}:{port}"
        assert defaults(origin) == "https://localhost:8443"
    caddyfile = (DEPLOY / "Caddyfile").read_text()
    assert "https://{$BOXEN_HOST:localhost}:8443 {" in caddyfile
    assert "tls internal" in caddyfile
    assert "skip_install_trust" in caddyfile
    assert "Strict-Transport-Security" not in caddyfile
    assert "reverse_proxy web:8000" in caddyfile
    assert "BOXEN_HTTPS_PORT" not in caddyfile


def test_proxy_bundles_configuration_and_keeps_ca_state_in_named_volumes():
    proxy = compose()["services"]["caddy"]
    assert proxy["image"] == "${BOXEN_CADDY_IMAGE:-boxen-caddy:0.1.0}"
    assert volumes(proxy) == {
        "/data": {"source": "caddy-data", "target": "/data", "read_only": False},
        "/config": {"source": "caddy-config", "target": "/config", "read_only": False},
    }
    assert "COPY deploy/Caddyfile /etc/caddy/Caddyfile" in (DEPLOY / "Dockerfile.caddy").read_text()


def test_builds_are_opt_in_and_share_the_root_ignore_file():
    builds = compose("compose.build.yaml")["services"]
    assert set(builds) == {"init", "web", "worker", "caddy"}
    for name in ("init", "web", "worker"):
        assert builds[name] == {"build": {"context": "..", "dockerfile": "Dockerfile", "target": "app"}}
    assert builds["caddy"] == {"build": {"context": "..", "dockerfile": "deploy/Dockerfile.caddy"}}
    assert compose("compose.ai-build.yaml")["services"] == {
        "boxen-ai": {"build": {"context": "..", "dockerfile": "Dockerfile", "target": "ai"}}
    }


def test_app_is_default_target_and_ai_inherits_app_with_cpu_libraries():
    dockerfile = (ROOT / "Dockerfile").read_text()
    stages = re.findall(r"^FROM (\S+)(?: AS ([\w-]+))?$", dockerfile, re.MULTILINE)
    assert stages[-1] == ("app-runtime", "app")
    assert stages[-2] == ("app-runtime", "ai")
    ai = dockerfile.split("FROM app-runtime AS ai\n")[1].split("FROM app-runtime AS app")[0]
    assert "libstdc++6 libgomp1 libssl3 zlib1g" in ai
    assert "USER 10001:10001" in ai
    assert 'ENTRYPOINT ["python", "-m", "boxen.analysis.infrastructure.runtime"]' in ai
    assert 'CMD ["--host", "0.0.0.0", "--threads", "8"]' in ai
    assert "BOXEN_DATA_DIR=/tmp/boxen-not-used BOXEN_AI_MODELS_DIR=/models" in ai
    assert not re.search(r"^COPY .*\.(gguf|safetensors)", dockerfile, re.MULTILINE)
    copy = "COPY scripts/import_container_profile.py /opt/boxen/tools/import_container_profile.py"
    assert dockerfile.index("COPY --from=python-build") < dockerfile.index(copy)
    assert dockerfile.index(copy) < dockerfile.index("FROM app-runtime AS ai")


def test_local_ai_shares_only_one_readonly_models_volume():
    local = compose("compose.ai-local.yaml")
    assert set(local["services"]) == {"web", "worker", "boxen-ai", "model-import"}
    assert local["volumes"] == {"boxen-models": None}
    for name in ("web", "worker", "boxen-ai"):
        service = local["services"][name]
        assert volumes(service) == {
            "/models": {"type": "volume", "source": "boxen-models", "target": "/models", "read_only": True}
        }
        assert service["environment"]["BOXEN_AI_MODE"] == "local"
        assert service["environment"]["BOXEN_AI_MODELS_DIR"] == "/models"
        assert service["environment"]["BOXEN_AI_PROFILE"].startswith("${BOXEN_AI_PROFILE:?")
        assert "build" not in service
        assert not service.get("ports")
    for name in ("web", "worker"):
        assert local["services"][name]["environment"]["BOXEN_AI_BASE_URL"] == "http://boxen-ai:8080"
    runtime = local["services"]["boxen-ai"]
    assert runtime["image"] == "${BOXEN_AI_IMAGE:-boxen-ai:0.1.0}"
    assert runtime["environment"]["BOXEN_DATA_DIR"] == "/tmp/boxen-not-used"
    assert runtime["networks"] == ["private"]
    assert runtime["command"] == ["--host", "0.0.0.0", "--threads", "${BOXEN_AI_THREADS:-8}"]
    assert runtime["stop_grace_period"] == "330s"
    assert not runtime.get("secrets")
    # AI availability does not prevent core inventory web/worker startup.
    assert not any(service.get("depends_on") for service in local["services"].values())


def test_model_import_is_explicit_and_network_disabled():
    service = compose("compose.ai-local.yaml")["services"]["model-import"]
    assert service["profiles"] == ["tools"]
    assert service["user"] == "0:0"
    assert service["cap_drop"] == ["ALL"]
    assert service["cap_add"] == ["CHOWN", "DAC_OVERRIDE"]
    assert service["network_mode"] == "none"
    assert service["read_only"] is True
    assert volumes(service) == {"/models": {"type": "volume", "source": "boxen-models", "target": "/models"}}
    assert not service.get("ports")
    assert not service.get("environment")


def test_remote_ai_requires_explicit_endpoint_and_readonly_metadata():
    remote = compose("compose.ai-remote.yaml")
    assert set(remote["services"]) == {"web", "worker"}
    assert remote["networks"] == {"egress": {}}
    assert not remote.get("secrets")
    assert not remote.get("volumes")
    for service in remote["services"].values():
        env = service["environment"]
        assert env["BOXEN_AI_MODE"] == "remote"
        assert env["BOXEN_AI_BASE_URL"].startswith("${BOXEN_AI_BASE_URL:?")
        assert env["BOXEN_AI_PROFILE"].startswith("${BOXEN_AI_PROFILE:?")
        assert env["BOXEN_AI_ALLOW_INSECURE_HTTP"] == "${BOXEN_AI_ALLOW_INSECURE_HTTP:-false}"
        assert env["BOXEN_AI_MODELS_DIR"] == "/models"
        assert not any(key.endswith("_FILE") for key in env)
        assert service["networks"] == ["private", "egress"]
        assert not service.get("ports")
        assert not service.get("secrets")
        assert set(volumes(service)) == {"/models"}
        metadata = volumes(service)["/models"]
        assert metadata["type"] == "bind"
        assert metadata["source"].startswith("${BOXEN_AI_PROFILES_DIR:?")
        assert metadata["read_only"] is True
        assert metadata["bind"] == {"create_host_path": False}


@pytest.mark.parametrize(
    "filename,variable,secret,source",
    [
        (
            "compose.ai-remote-auth.yaml",
            "BOXEN_AI_API_KEY_FILE",
            "boxen_ai_api_key",
            "BOXEN_AI_API_KEY_SOURCE",
        ),
        ("compose.ai-remote-ca.yaml", "BOXEN_AI_CA_FILE", "boxen_ai_ca", "BOXEN_AI_CA_SOURCE"),
    ],
)
def test_credentials_and_private_ca_are_separate_opt_in_file_secrets(filename, variable, secret, source):
    overlay = compose(filename)
    assert set(overlay["services"]) == {"web", "worker"}
    assert set(overlay["secrets"]) == {secret}
    assert overlay["secrets"][secret]["file"].startswith("${" + source + ":?")
    for service in overlay["services"].values():
        assert service["environment"] == {variable: f"/run/secrets/{secret}"}
        assert service["secrets"] == [secret]


def test_example_env_has_safe_defaults_and_no_empty_optional_file_variables():
    example = dict(
        line.split("=", 1)
        for line in (DEPLOY / ".env.example").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    assert example["BOXEN_IMAGE"] == "boxen:0.1.0"
    assert example["BOXEN_CADDY_IMAGE"] == "boxen-caddy:0.1.0"
    assert example["BOXEN_AI_IMAGE"] == "boxen-ai:0.1.0"
    assert example["BOXEN_HOST"] == "localhost"
    assert example["BOXEN_BIND_ADDRESS"] == "127.0.0.1"
    assert example["BOXEN_HTTPS_PORT"] == "8443"
    assert example["BOXEN_AI_PROFILE"] == ""
    assert example["BOXEN_AI_ALLOW_INSECURE_HTTP"] == "false"
    assert "BOXEN_ORIGIN" not in example
    assert "BOXEN_AI_BASE_URL" not in example
    assert not any(key.endswith("_FILE") for key in example)


@pytest.mark.parametrize(
    "path",
    [
        ".local/inventory/photo.jpg",
        ".runtime/db/boxen.sqlite3",
        ".runtime.quarantine-old/db/boxen.sqlite3",
        "deploy/.env",
        "deploy/.env.production",
        "deploy/.env.example",
        "backend/boxen/.env.private",
        "frontend/public/.local/photo.jpg",
        "frontend/public/keys/key",
        "frontend/src/secrets/api-token",
        "backend/boxen/models/profile/manifest.json",
        "backend/boxen/tmp/source-photo.jpg",
        "frontend/public/temp/credential",
        "backend/boxen/data/media/photo.jpg",
        "backend/boxen/backups/snapshot/archive.zip",
        "frontend/public/certificates/private.key",
        "frontend/public/certificates/private.pem",
        "backend/boxen/id_ed25519",
        "backend/boxen/id_rsa",
        "backend/boxen/session.db",
        "backend/boxen/session.db-wal",
        "backend/boxen/weights.gguf",
        "frontend/public/weights.safetensors",
        "frontend/src/debug.log",
        "backend/boxen/__pycache__/config.pyc",
        "frontend/node_modules/package/index.js",
        "frontend/test-results-lan/screenshot.png",
        "backend/boxen/static/index.html",
    ],
)
def test_private_and_generated_paths_cannot_be_reincluded_in_build_context(path):
    rules = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert rules[0] == "**"
    last_allow = max(index for index, rule in enumerate(rules) if rule.startswith("!"))
    # Test the final exclusion block against each file and all directory prefixes.
    # No later negation can reverse any of these exclusions.
    candidates = [PurePosixPath(path), *PurePosixPath(path).parents]
    assert any(candidate.full_match(rule) for rule in rules[last_allow + 1 :] for candidate in candidates)


def test_build_context_allowlist_includes_source_and_profile_import_tool():
    rules = (ROOT / ".dockerignore").read_text().splitlines()
    for path in (
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "frontend/pnpm-workspace.yaml",
        "frontend/index.html",
        "frontend/vite.config.ts",
        "frontend/tsconfig.json",
        "deploy/Dockerfile.caddy",
        "deploy/Caddyfile",
        "scripts/import_container_profile.py",
    ):
        assert f"!{path}" in rules
        assert (ROOT / path).is_file()
    assert "!backend/boxen/**" in rules
    assert "!frontend/src/**" in rules
    assert "!frontend/public/**" in rules
