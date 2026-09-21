import json
import os
import subprocess
import sys

from boxen.operations.infrastructure.database import initialize


def command(settings, *arguments):
    environment = {
        **os.environ,
        "BOXEN_ENV": "test",
        "BOXEN_ORIGIN": settings.origin,
        "BOXEN_DATA_DIR": str(settings.data_dir),
        "BOXEN_DISK_RESERVE_BYTES": "0",
        "BOXEN_DISK_RESERVE_PERCENT": "0",
        "BOXEN_ANONYMOUS_ACCESS": "off",
    }
    return subprocess.run(
        [sys.executable, "-m", "boxen.cli", *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_cli_initialization_verification_and_empty_derivative_repair(settings):
    first = command(settings, "init")
    assert first.returncode == 0
    second = command(settings, "init")
    assert second.returncode == 0 and "already initialized" in second.stdout
    for args in [("verify",), ("restore", "verify"), ("repair-derivatives",), ("worker", "--once")]:
        result = command(settings, *args)
        assert result.returncode == 0, result.stderr


def test_cli_backup_shares_runtime_lock_but_derivative_repair_requires_stopped_services(client, settings):
    backup = command(settings, "backup")
    assert backup.returncode == 0, backup.stderr
    assert json.loads(backup.stdout)["status"] == "verified"
    repair = command(settings, "repair-derivatives")
    assert repair.returncode != 0
    assert "Stop services" in repair.stderr


def test_cli_verify_returns_failure_for_invalid_search_projection(client, settings):
    client.post("/api/v1/boxes", json={"name": "Verification fixture"})
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.execute("DELETE FROM box_search")
    result = command(settings, "verify")
    assert result.returncode == 1
    assert json.loads(result.stdout)["search"]["mismatches"] == 1


def test_cli_wildcard_requires_a_browser_origin(settings):
    initialize(settings)
    result = command(settings, "web", "--host", "0.0.0.0")
    assert result.returncode != 0 and "wildcard bind needs a browser address" in result.stderr
