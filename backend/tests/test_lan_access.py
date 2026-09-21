import io
import os
import sys

import pytest
from boxen import cli
from boxen.api.app import create_app
from boxen.operations.infrastructure.database import initialize
from boxen.platform.config import Settings
from PIL import Image
from pydantic import ValidationError
from test_anonymous_access import browser, session


@pytest.mark.parametrize("host", ["192.0.2.10", "boxen.local", "fd00::177", "127.0.0.1"])
def test_native_bind_derives_exact_origin_from_old_loopback_configuration(tmp_path, host):
    settings = Settings(env="development", origin="http://127.0.0.1:8000", data_dir=tmp_path)
    configured = cli.web_settings(settings, host, 8123)
    authority = f"[{host}]" if ":" in host else host
    assert configured.origin == f"http://{authority}:8123"
    assert configured.anonymous_access == "editor"
    assert settings.origin == "http://127.0.0.1:8000"


def test_development_bind_without_a_configured_origin(tmp_path):
    settings = Settings(env="development", data_dir=tmp_path)
    assert cli.web_settings(settings, "192.0.2.10", 8000).origin == "http://192.0.2.10:8000"


@pytest.mark.parametrize("bind", ["0.0.0.0", "::"])
def test_wildcard_bind_uses_explicit_canonical_origin(tmp_path, bind):
    settings = Settings(env="development", origin="http://127.0.0.1:8000", data_dir=tmp_path)
    with pytest.raises(ValueError, match="wildcard bind"):
        cli.web_settings(settings, bind, 8000)
    assert cli.web_settings(settings, bind, 8000, "http://192.0.2.10:8000").origin == (
        "http://192.0.2.10:8000"
    )


def test_explicit_https_reverse_proxy_origin_is_preserved(tmp_path):
    settings = Settings(env="production", origin="https://boxen.local:8443", data_dir=tmp_path)
    assert cli.web_settings(settings, "0.0.0.0", 8000).origin == settings.origin
    with pytest.raises(ValidationError, match="Production access requires HTTPS"):
        cli.web_settings(settings, "192.0.2.10", 8000, "http://192.0.2.10:8000")


@pytest.mark.parametrize(
    "origin",
    [
        "http://",
        "http://0.0.0.0:8000",
        "http://[::]:8000",
        "http://boxen:0",
        "http://boxen:99999",
        "http://user:pass@boxen",
        "http://boxen/path",
    ],
)
def test_invalid_browser_origins_are_not_wildcarded(origin):
    with pytest.raises(ValueError):
        Settings(env="development", origin=origin)


def test_exact_reported_cli_command_reaches_server_start(tmp_path, monkeypatch, capsys):
    for key in list(os.environ):
        if key.startswith("BOXEN_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("BOXEN_ENV", "development")
    monkeypatch.setenv("BOXEN_ORIGIN", "http://127.0.0.1:8000")
    monkeypatch.setenv("BOXEN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["boxen", "web", "--host", "192.0.2.10", "--port", "8000"])
    initialize(Settings.load())
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    cli.main()
    app, options = calls[0]
    assert options["host"] == "192.0.2.10" and options["port"] == 8000
    assert app.state.services.settings.origin == "http://192.0.2.10:8000"
    assert "Anonymous access: editor" in capsys.readouterr().out
    app.state.services.database.close()


def test_anonymous_lan_inventory_without_owner_setup(tmp_path):
    settings = Settings(env="development", origin="http://192.0.2.10:8000", data_dir=tmp_path)
    initialize(settings)
    with browser(create_app(settings), settings.origin) as phone:
        current = session(phone)
        assert current.json()["anonymous"] is True
        assert "box.edit" in current.json()["capabilities"]
        assert "Secure" not in current.headers["set-cookie"]
        created = phone.post("/api/v1/boxes", json={"name": "Garage", "description_markdown": "## Tools"})
        assert created.status_code == 201, created.text
        code = created.json()["code"]
        changed = phone.patch(
            f"/api/v1/boxes/{code}",
            headers={"If-Match": created.headers["etag"]},
            json={"name": "Garage shelf"},
        )
        assert changed.status_code == 200
        item = phone.post(f"/api/v1/boxes/{code}/items", json={"name": "Hammer", "quantity": "2"})
        assert item.status_code == 201
        image = io.BytesIO()
        Image.new("RGB", (50, 50), "blue").save(image, "PNG")
        photo = phone.post(
            f"/api/v1/boxes/{code}/images", files={"file": ("tools.png", image.getvalue(), "image/png")}
        )
        assert photo.status_code == 201
        assert code in phone.get("/api/v1/search?q=Hammer").text
        resolved = phone.post("/api/v1/codes/resolve", json={"input": "boxen:v1:" + code})
        assert resolved.status_code == 200
        assert resolved.json()["box"]["code"] == code
        assert phone.get("/api/v1/users").status_code == 403
        assert phone.get("/api/v1/setup/status").json()["setup_required"] is True
        assert (
            phone.post(
                "/api/v1/boxes", json={"name": "Denied"}, headers={"Origin": "http://evil.test"}
            ).status_code
            == 403
        )
        assert phone.get("/api/v1/boxes", headers={"Host": "evil.test"}).status_code == 400
