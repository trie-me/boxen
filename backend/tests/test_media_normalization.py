import hashlib
import io

import pytest
from boxen.api.app import create_app
from boxen.media.infrastructure.storage import file_hash
from boxen.operations.infrastructure.database import initialize
from boxen.platform.application import Application
from boxen.shared.values import new_id
from fastapi.testclient import TestClient
from PIL import Image
from test_cli import command
from test_workflows import create_box


def encoded(image, format, **options):
    output = io.BytesIO()
    image.save(output, format, **options)
    return output.getvalue()


def upload(client, code, content, name="photo.jpg"):
    return client.post(
        f"/api/v1/boxes/{code}/images",
        headers={"Idempotency-Key": new_id()},
        files={"file": (name, content, "application/octet-stream")},
    )


@pytest.mark.parametrize(
    "format,size,expected",
    [
        ("JPEG", (3600, 1800), (2048, 1024)),
        ("PNG", (1800, 3600), (1024, 2048)),
        ("WEBP", (3000, 3000), (2048, 2048)),
        ("JPEG", (320, 240), (320, 240)),
        ("PNG", (1, 1), (1, 1)),
    ],
)
def test_upload_stores_only_bounded_webp_and_thumbnail(client, format, size, expected):
    code = create_box(client).json()["code"]
    source = encoded(Image.new("RGB", size, "coral"), format)
    response = upload(client, code, source)
    assert response.status_code == 201, response.text
    photo = response.json()
    original = client.get(f"/api/v1/images/{photo['id']}/content?variant=original")
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/webp"
    assert hashlib.sha256(original.content).hexdigest() == photo["sha256"]
    with Image.open(io.BytesIO(original.content)) as image:
        assert image.format == "WEBP"
        assert image.size == expected
    assert client.get(photo["display_url"]).content == original.content
    with Image.open(io.BytesIO(client.get(photo["thumbnail_url"]).content)) as image:
        assert image.format == "WEBP"
        assert max(image.size) <= min(480, max(expected))

    app = client.app.state.services
    with app.database.transaction() as repo:
        row = repo.one("box_images", id=photo["id"])
        assert (row["width"], row["height"]) == expected
        assert row["byte_size"] == len(original.content)
        assert row["media_type"] == "image/webp"
        assert row["display_storage_key"] == row["original_storage_key"]
        assert app.media.store.verify(repo) == {"checked": 1, "missing_originals": 0, "corrupt_originals": 0}
    files = [path for path in app.media.store.root.rglob("*") if path.is_file()]
    assert len(files) == 2
    assert all(path.suffix == ".webp" and path.read_bytes() != source for path in files)
    assert not list((app.media.store.root / "staging").iterdir())
    if max(size) > 2048:
        assert len(original.content) < len(source)


def test_camera_orientation_is_applied_and_metadata_removed(client):
    code = create_box(client).json()["code"]
    image = Image.new("RGB", (300, 100), "red")
    image.paste("blue", (150, 0, 300, 100))
    exif = Image.Exif()
    exif[274] = 6  # Camera held in portrait orientation: rotate clockwise.
    exif[315] = "Metadata that must not be stored"
    response = upload(client, code, encoded(image, "JPEG", exif=exif, icc_profile=b"test profile"))
    assert response.status_code == 201, response.text
    with Image.open(io.BytesIO(client.get(response.json()["display_url"]).content)) as stored:
        assert stored.size == (100, 300)
        assert not stored.getexif()
        assert not any(key in stored.info for key in ("exif", "icc_profile", "xmp"))
        top, bottom = stored.getpixel((50, 50)), stored.getpixel((50, 250))
        assert top[0] > 240 and top[2] < 15
        assert bottom[2] > 240 and bottom[0] < 15


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_png_transparency_survives_normalization(client, mode):
    code = create_box(client).json()["code"]
    image = Image.new("RGBA", (80, 80), (255, 0, 0, 0))
    image.paste((0, 255, 0, 255), (20, 20, 60, 60))
    image = image.convert(mode)
    response = upload(client, code, encoded(image, "PNG"), "transparent.png")
    assert response.status_code == 201, response.text
    with Image.open(io.BytesIO(client.get(response.json()["display_url"]).content)) as stored:
        assert stored.mode == "RGBA"
        assert stored.getpixel((0, 0))[3] == 0
        assert stored.getpixel((40, 40))[3] == 255


def test_duplicates_and_rejected_uploads_leave_no_staged_files(client):
    box = create_box(client).json()
    image = Image.new("RGB", (600, 400), "blue")
    source = encoded(image, "PNG")
    first, second = upload(client, box["code"], source), upload(client, box["code"], source)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    app = client.app.state.services
    store = app.media.store.root
    before = {path for path in store.rglob("*") if path.is_file()}
    animation = encoded(image, "WEBP", save_all=True, append_images=[Image.new("RGB", image.size, "red")])
    for invalid in (b"not an image", animation):
        assert upload(client, box["code"], invalid).status_code == 422
    app.media.settings = app.media.settings.model_copy(update={"max_image_pixels": 100})
    assert upload(client, box["code"], source).status_code == 422
    app.media.settings = app.media.settings.model_copy(update={"max_image_pixels": 50_000_000})
    # Processing can succeed before attaching to an archived box is rejected.
    current = client.get(f"/api/v1/boxes/{box['code']}")
    archived = client.post(
        f"/api/v1/boxes/{box['code']}/archive", headers={"If-Match": current.headers["etag"]}
    )
    assert archived.status_code == 200, archived.text
    assert upload(client, box["code"], source).status_code == 409
    assert not list((store / "staging").iterdir())
    assert {path for path in store.rglob("*") if path.is_file()} == before


def test_backup_restore_and_derivative_repair_preserve_webp_and_legacy_originals(settings):
    token = initialize(settings)
    expected = {}
    with TestClient(create_app(settings)) as client:
        client.headers["Origin"] = settings.origin
        setup = client.post(
            "/api/v1/setup/owner",
            headers={"X-Boxen-Setup-Token": token},
            json={"username": "owner", "display_name": "Owner", "password": "media-test-passphrase"},
        )
        assert setup.status_code == 201, setup.text
        client.headers["X-CSRF-Token"] = setup.json()["csrf_token"]
        code = create_box(client).json()["code"]
        app = client.app.state.services
        for format, color in (("WEBP", "blue"), ("JPEG", "orange"), ("PNG", "green")):
            source = encoded(Image.new("RGB", (3000, 1500), color), format)
            result = upload(client, code, source)
            assert result.status_code == 201, result.text
            image_id = result.json()["id"]
            if format != "WEBP":
                # Seed a pre-normalization record, including its immutable raw original.
                staged = app.media.stage(io.BytesIO(source))
                digest = file_hash(staged)
                key = app.media.store.commit(staged, "originals", digest, format.lower())
                with app.database.transaction(write=True) as repo:
                    repo.update(
                        "box_images",
                        {
                            "original_storage_key": key,
                            "sha256": digest,
                            "byte_size": len(source),
                            "width": 3000,
                            "height": 1500,
                            "media_type": "image/" + format.lower(),
                            "derivative_renderer_version": "pillow-webp-v1",
                        },
                        id=image_id,
                    )
            original = client.get(f"/api/v1/images/{image_id}/content?variant=original")
            assert original.status_code == 200
            assert original.headers["content-type"] == "image/" + format.lower()
            if format != "WEBP":
                assert original.content == source
            with app.database.transaction() as repo:
                row = repo.one("box_images", id=image_id)
            expected[image_id] = row, original.content

        app.backups.create({"relative_path": "normalization-test"})
        with app.database.transaction() as repo:
            installation = repo.setting("installation_id")
    offline = Application(settings)
    try:
        offline.backups.restore(settings.data_dir / "backups/normalization-test", installation, apply=True)
    finally:
        offline.database.close()
    repair = command(settings, "repair-derivatives")
    assert repair.returncode == 0, repair.stderr
    restored = Application(settings)
    try:
        with restored.database.transaction() as repo:
            assert restored.media.store.verify(repo) == {
                "checked": 3,
                "missing_originals": 0,
                "corrupt_originals": 0,
            }
            for image_id, (before, content) in expected.items():
                after = repo.one("box_images", id=image_id)
                for field in ("original_storage_key", "sha256", "byte_size", "media_type", "width", "height"):
                    assert after[field] == before[field]
                assert restored.media.store.path(after["original_storage_key"]).read_bytes() == content
                for variant, edge in (("display", 2048), ("thumbnail", 480)):
                    with Image.open(restored.media.store.path(after[variant + "_storage_key"])) as image:
                        assert image.format == "WEBP"
                        assert image.size == (edge, edge // 2)
        assert not list((restored.media.store.root / "staging").iterdir())
    finally:
        restored.database.close()
