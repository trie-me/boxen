"""Batch label API and physical Letter geometry, including QR scanability."""

import io
import math
import subprocess

import pytest
import zxingcpp
from boxen.catalog.domain import BoxCode
from boxen.labeling.infrastructure.pdf import LabelRenderer
from boxen.platform.config import Settings
from boxen.shared.errors import DomainError
from boxen.shared.values import new_id, now
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.units import mm
from test_anonymous_access import browser, session
from test_label_layout import text_runs
from test_organization import archive, box, box_url, collection, patch, snapshot


def sample_boxes(count):
    return [
        {"public_code": BoxCode.from_payload(f"{i:07d}").value, "name": f"Workshop {i + 1}", "version": 1}
        for i in range(count)
    ]


@pytest.fixture(scope="module")
def renderer():
    return LabelRenderer(Settings().assets)


def reader(data):
    return PdfReader(io.BytesIO(data))


@pytest.mark.parametrize(
    "count,start", [(1, 1), (10, 1), (11, 1), (21, 1), (1, 10), (2, 10), (10, 2), (500, 10)]
)
def test_letter_pages_positions_and_no_duplicate_labels(renderer, count, start):
    boxes = sample_boxes(count)
    pdf = reader(renderer.render_sheet(boxes, start)[0])
    assert len(pdf.pages) == math.ceil((count + start - 1) / 10)
    assert pdf.trailer["/Root"]["/ViewerPreferences"]["/PrintScaling"] == "/None"
    assert pdf.trailer["/Root"]["/ViewerPreferences"]["/Duplex"] == "/Simplex"
    seen = []
    for page_index, page in enumerate(pdf.pages):
        assert tuple(page.mediabox) == (0, 0, 612, 792)
        runs = text_runs(page)
        codes = [run for run in runs if run.font == "BoxenMono"]
        for run in codes:
            index = len(seen)
            absolute = index + start - 1
            assert absolute // 10 == page_index
            row, col = divmod(absolute % 10, 2)
            # Avery Letter 5163 geometry: 5/32-inch side margin, 3/16-inch gutter.
            left = 11.25 + col * 301.5
            bottom = 612 - row * 144
            assert run.x == pytest.approx(left + 47 * mm, abs=0.001)
            assert run.y == pytest.approx(bottom + 3 * mm + 13, abs=0.001)
            assert run.text == boxes[index]["public_code"]
            assert left <= run.x < run.right <= left + 288
            assert bottom <= run.bottom < run.top <= bottom + 144
            seen.append(run.text)
        assert len([run for run in runs if run.text == "BOXEN"]) == len(codes)
    assert seen == [box["public_code"] for box in boxes]


def test_offsets_long_names_and_etags(renderer):
    boxes = sample_boxes(11)
    boxes[0]["name"] = "W" * 120
    original = renderer.render_sheet(boxes)
    assert renderer.render_sheet(boxes) == original
    moved = renderer.render_sheet(boxes, offset_x_mm=3, offset_y_mm=-3)
    assert moved[1] != original[1]
    for before_page, after_page in zip(reader(original[0]).pages, reader(moved[0]).pages):
        for before, after in zip(text_runs(before_page), text_runs(after_page)):
            assert after.x - before.x == pytest.approx(3 * mm, abs=0.001)
            assert after.y - before.y == pytest.approx(3 * mm, abs=0.001)
            assert 0 <= after.x < after.right < 612
            assert 0 <= after.bottom < after.top < 792
    assert "…" in reader(original[0]).pages[0].extract_text()
    boxes[0]["name"] = "Renamed"
    assert renderer.render_sheet(boxes)[1] != original[1]
    assert renderer.render_sheet(list(reversed(boxes)))[1] != original[1]


def test_every_label_decodes_at_print_resolution(renderer, tmp_path):
    boxes = sample_boxes(11)
    path = tmp_path / "labels.pdf"
    path.write_bytes(renderer.render_sheet(boxes)[0])
    subprocess.run(
        ["pdftoppm", "-r", "150", "-png", str(path), str(tmp_path / "page")], check=True, capture_output=True
    )
    decoded = []
    for path in sorted(tmp_path.glob("page-*.png")):
        with Image.open(path) as image:
            decoded += [result.text for result in zxingcpp.read_barcodes(image)]
    assert sorted(decoded) == sorted("boxen:v1:" + box["public_code"] for box in boxes)


def test_pin_pdf_order_current_names_no_database_mutations(client):
    first, second = box(client, "First"), box(client, "Second")
    codes = [second.json()["code"], first.json()["code"]]
    before = snapshot(client)
    response = client.post("/api/v1/labels.pdf", json={"box_codes": codes})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="boxen-labels-letter.pdf"'
    assert snapshot(client) == before
    text = reader(response.content).pages[0].extract_text()
    assert text.index("Second") < text.index("First")
    assert all(text.count(code) == 1 for code in codes)
    assert client.post("/api/v1/labels.pdf", json={"box_codes": codes}).content == response.content
    patch(client, box_url(first), {"name": "Current name"})
    renamed = client.post("/api/v1/labels.pdf", json={"box_codes": codes})
    assert "Current name" in reader(renamed.content).pages[0].extract_text()
    assert renamed.headers["etag"] != response.headers["etag"]


def test_collection_all_members_including_archived_and_updated_membership(client):
    z, a = box(client, "Zulu"), box(client, "Alpha")
    group = collection(client, box_codes=[z.json()["code"], a.json()["code"]])
    archive(client, a)
    response = client.post(
        "/api/v1/labels.pdf", json={"collection_id": group.json()["id"], "start_position": 10}
    )
    assert response.status_code == 200, response.text
    pages = reader(response.content).pages
    assert len(pages) == 2
    assert "Alpha" in pages[0].extract_text() and "Zulu" in pages[1].extract_text()
    box(client, "Middle", collection_ids=[group.json()["id"]])
    response = client.post("/api/v1/labels.pdf", json={"collection_id": group.json()["id"]})
    assert "Middle" in reader(response.content).pages[0].extract_text()


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"box_codes": []},
        {"box_codes": ["bad"]},
        {"box_codes": ["BX-0000-0004"] * 501},
        {"collection_id": "bad"},
    ],
)
def test_invalid_selection(client, extra):
    assert client.post("/api/v1/labels.pdf", json=extra).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"start_position": 0},
        {"start_position": 11},
        {"start_position": 1.5},
        {"offset_x_mm": 3.1},
        {"offset_y_mm": -3.1},
        {"offset_x_mm": "x"},
        {"unknown": 1},
        {"collection_id": "00000000-0000-4000-8000-000000000000"},
    ],
)
def test_invalid_layout_or_ambiguous_source(client, extra):
    code = box(client).json()["code"]
    assert client.post("/api/v1/labels.pdf", json={"box_codes": [code], **extra}).status_code == 422


def test_duplicates_empty_missing_and_purged_fail_atomically(client):
    created = box(client)
    code = created.json()["code"]
    assert client.post("/api/v1/labels.pdf", json={"box_codes": [code, code]}).status_code == 422
    empty = collection(client)
    response = client.post("/api/v1/labels.pdf", json={"collection_id": empty.json()["id"]})
    assert response.status_code == 422 and response.json()["code"] == "label.count_invalid"
    assert (
        client.post(
            "/api/v1/labels.pdf", json={"collection_id": "00000000-0000-4000-8000-000000000000"}
        ).status_code
        == 404
    )
    archived = archive(client, created)
    with client.app.state.services.database.transaction(write=True) as repo:
        repo.insert(
            "backups",
            {
                "id": new_id(),
                "status": "verified",
                "relative_path": "fixture-only",
                "format_version": 1,
                "schema_version": "0002",
                "requested_by": repo.find("users", role="owner")[0]["id"],
                "created_at": now(),
                "verified_at": now(),
            },
        )
    assert (
        client.post(
            box_url(created) + "/purge",
            json={"confirmation_code": code},
            headers={"If-Match": archived.headers["etag"]},
        ).status_code
        == 204
    )
    other = box(client, "Other").json()["code"]
    response = client.post("/api/v1/labels.pdf", json={"box_codes": [other, code]})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_session_editor_origin_csrf_and_rate_limit(client, settings):
    code = box(client).json()["code"]
    body = {"box_codes": [code]}
    settings.anonymous_access = "viewer"
    with browser(client.app, settings.origin) as visitor:
        assert visitor.post("/api/v1/labels.pdf", json=body).status_code == 401
        session(visitor)
        assert visitor.post("/api/v1/labels.pdf", json=body).status_code == 403
        settings.anonymous_access = "editor"
        session(visitor)
        assert visitor.post("/api/v1/labels.pdf", json=body).status_code == 200
    for headers in [{"Origin": "https://wrong.invalid"}, {"X-CSRF-Token": "wrong"}]:
        assert client.post("/api/v1/labels.pdf", json=body, headers=headers).status_code == 403
    for _ in range(30):
        assert client.post("/api/v1/labels.pdf", json=body).status_code == 200
    assert client.post("/api/v1/labels.pdf", json=body).status_code == 429


def test_renderer_bounds(renderer):
    for boxes in [[], sample_boxes(501)]:
        with pytest.raises(DomainError):
            renderer.render_sheet(boxes)
