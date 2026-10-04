"""Collection membership on printed labels, including live lookups and scanability."""

import io
import subprocess
import unicodedata

import pytest
import zxingcpp
from boxen.catalog.domain import BoxCode
from boxen.labeling.infrastructure.pdf import LabelRenderer
from boxen.platform.config import Settings
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.units import mm
from test_label_layout import EPSILON, PROFILE_CASES, label_cells, text_runs
from test_label_sheet import sample_boxes
from test_organization import box, box_url, collection, collection_url, patch, snapshot


@pytest.fixture(scope="module")
def renderer():
    return LabelRenderer(Settings().assets)


@pytest.fixture
def label_box():
    return {
        "public_code": BoxCode.from_payload("7K3MR9Q").value,
        "name": "Tools",
        "version": 1,
    }


def read_pdf(data):
    return PdfReader(io.BytesIO(data))


def collection_text(runs):
    return " ".join(run.text for run in runs if run.font == "BoxenSans" and run.text != "BOXEN")


def get_labels(client, created, source, selected):
    if source in {profile[0] for profile in PROFILE_CASES}:
        response = client.get(box_url(created) + "/label.pdf", params={"profile": source})
    elif source == "pins":
        response = client.post("/api/v1/labels.pdf", json={"box_codes": [created.json()["code"]]})
    else:
        assert source == "collection"
        response = client.post("/api/v1/labels.pdf", json={"collection_id": selected.json()["id"]})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    return response


@pytest.mark.parametrize("source", [profile[0] for profile in PROFILE_CASES] + ["pins", "collection"])
def test_api_prints_all_current_collections_in_stable_name_order(client, source):
    created = box(client, "Tools")
    # Creation and selection order differ from the canonical membership order.
    last = collection(client, "Zulu", box_codes=[created.json()["code"]])
    collection(client, "alpha", box_codes=[created.json()["code"]])
    collection(client, "Unrelated")
    before = snapshot(client)
    response = get_labels(client, created, source, last)
    assert snapshot(client) == before, "Generating labels must not alter inventory or audit history"
    repeated = get_labels(client, created, source, last)
    assert repeated.content == response.content
    assert repeated.headers["etag"] == response.headers["etag"]
    pages = read_pdf(response.content).pages
    assert len(pages) == 1
    runs = text_runs(pages[0])
    count = 14 if source == "sheet-a4-2x7-v1" else 1
    printed = collection_text(runs)
    assert printed.count("alpha") == printed.count("Zulu") == count
    assert printed.index("alpha") < printed.index("Zulu")
    assert "Unrelated" not in pages[0].extract_text()
    assert [run.text for run in runs if run.font == "BoxenBold"] == ["Tools"] * count
    assert [run.text for run in runs if run.font == "BoxenMono"] == [created.json()["code"]] * count


@pytest.mark.parametrize("source", ["sheet-4x2-in-v1", "pins", "collection"])
def test_api_refreshes_pdf_and_etag_after_rename_membership_removal_and_delete(client, source):
    created = box(client, "Tools")
    selected = collection(client, "Main", box_codes=[created.json()["code"]])
    changed = collection(client, "Gear", box_codes=[created.json()["code"]])
    previous = get_labels(client, created, source, selected)
    assert "Gear" in collection_text(text_runs(read_pdf(previous.content).pages[0]))

    def assert_changed(expected, absent):
        nonlocal previous
        current = get_labels(client, created, source, selected)
        assert current.content != previous.content
        assert current.headers["etag"] != previous.headers["etag"]
        printed = collection_text(text_runs(read_pdf(current.content).pages[0]))
        assert "Main" in printed
        for value in expected:
            assert value in printed
        for value in absent:
            assert value not in printed
        previous = current

    renamed = patch(client, collection_url(changed), {"name": "Trip"})
    assert renamed.status_code == 200
    assert_changed(["Trip"], ["Gear"])
    removed = patch(client, collection_url(changed), {"box_codes": []})
    assert removed.status_code == 200
    assert_changed([], ["Trip", "Gear"])
    added = patch(client, box_url(created), {"collection_ids": [selected.json()["id"], changed.json()["id"]]})
    assert added.status_code == 200
    assert_changed(["Trip"], ["Gear"])
    current_collection = client.get(collection_url(changed))
    deleted = client.delete(collection_url(changed), headers={"If-Match": current_collection.headers["etag"]})
    assert deleted.status_code == 204
    assert_changed([], ["Trip", "Gear"])


@pytest.mark.parametrize("source", ["pins", "collection"])
def test_batch_keeps_each_box_membership_with_its_own_label(client, source):
    first, second, ungrouped = box(client, "Alpha"), box(client, "Zulu"), box(client, "Ungrouped")
    selected = collection(client, "Main", box_codes=[first.json()["code"], second.json()["code"]])
    collection(client, "Garden", box_codes=[first.json()["code"]])
    collection(client, "Trip", box_codes=[second.json()["code"]])
    expected = {
        first.json()["code"]: ["Garden", "Main"],
        second.json()["code"]: ["Main", "Trip"],
        ungrouped.json()["code"]: [],
    }
    codes = [second.json()["code"], ungrouped.json()["code"], first.json()["code"]]
    body = {"box_codes": codes} if source == "pins" else {"collection_id": selected.json()["id"]}
    response = client.post("/api/v1/labels.pdf", json=body)
    assert response.status_code == 200, response.text
    runs = text_runs(read_pdf(response.content).pages[0])
    printed_codes = [run.text for run in runs if run.font == "BoxenMono"]
    assert printed_codes == (codes if source == "pins" else [first.json()["code"], second.json()["code"]])
    for index, code in enumerate(printed_codes):
        row, col = divmod(index, 2)
        x, y = 11.25 + col * 301.5, 612 - row * 144
        cell = [run for run in runs if x <= run.x < x + 288 and y <= run.y < y + 144]
        printed = collection_text(cell)
        for name in {"Garden", "Main", "Trip"}:
            assert (name in printed) == (name in expected[code])


@pytest.mark.parametrize("profile", PROFILE_CASES, ids=[case[0] for case in PROFILE_CASES])
def test_no_membership_adds_no_collection_text_or_layout_change(renderer, label_box, profile):
    default = renderer.render(label_box, profile[0])
    explicit_empty = renderer.render({**label_box, "collection_names": []}, profile[0])
    assert explicit_empty == default
    runs = text_runs(read_pdf(default[0]).pages[0])
    assert collection_text(runs) == ""
    assert [run.text for run in runs if run.font == "BoxenSans"] == ["BOXEN"] * profile[3]


@pytest.mark.parametrize("profile", PROFILE_CASES, ids=[case[0] for case in PROFILE_CASES])
def test_collection_content_changes_pdf_and_etag_without_box_version_change(renderer, label_box, profile):
    plain = renderer.render(label_box, profile[0])
    grouped = renderer.render({**label_box, "collection_names": ["Camping"]}, profile[0])
    renamed = renderer.render({**label_box, "collection_names": ["Garden"]}, profile[0])
    assert len({plain[0], grouped[0], renamed[0]}) == 3
    assert len({plain[1], grouped[1], renamed[1]}) == 3
    assert renderer.render({**label_box, "collection_names": ["Camping"]}, profile[0]) == grouped


@pytest.mark.parametrize("layout", [profile[0] for profile in PROFILE_CASES] + ["batch"])
def test_full_membership_affects_etag_even_when_changed_name_is_ellipsized(renderer, label_box, layout):
    def render(tail):
        value = {**label_box, "collection_names": ["A" * 120, tail]}
        return renderer.render_sheet([value]) if layout == "batch" else renderer.render(value, layout)

    before, old_etag = render("Yesterday")
    after, new_etag = render("Tomorrow")
    # The first name fills all available collection lines; the changed tail is hidden.
    assert collection_text(text_runs(read_pdf(before).pages[0])) == collection_text(
        text_runs(read_pdf(after).pages[0])
    )
    assert new_etag != old_etag, "Even omitted names must participate in cache invalidation"


LONG_CASES = [
    ("W" * 120, ["W" * 120]),
    (("gypq precision tools " * 6)[:120], [("Long collection and spares " * 5)[:120]]),
    ("Ångström café", ["Cafe\u0301 parts", "Été"]),
    ("Tools", [f"Collection {index:02d}" for index in range(30)]),
]


def assert_cell_geometry(runs, cell, compact=False, sheet=False):
    x, y, width, height = cell
    selected = [run for run in runs if x <= run.x < x + width and y <= run.y < y + height]
    names = [run for run in selected if run.font == "BoxenBold"]
    codes = [run for run in selected if run.font == "BoxenMono"]
    collections = [run for run in selected if run.font == "BoxenSans" and run.text != "BOXEN"]
    assert 1 <= len(names) <= 2
    assert len(codes) == 1
    assert 1 <= len(collections) <= (1 if compact else 2)
    margin = (2 if compact or sheet else 3) * mm
    qr_size = (25 if compact else 30 if sheet else 40) * mm
    gap = (2 if compact else 4) * mm
    for run in selected:
        assert run.x >= x + margin + qr_size + gap - EPSILON, "Text entered the QR quiet zone"
        assert run.right <= x + width - margin + EPSILON, run
        assert run.bottom >= y - EPSILON, run
        assert run.top <= y + height + EPSILON, run
    assert min(run.bottom for run in names) > max(run.top for run in collections), "Name overlaps collection"
    assert min(run.bottom for run in collections) > codes[0].top, "Collection overlaps typeable code"
    for upper, lower in zip(collections, collections[1:]):
        assert upper.y - lower.y >= upper.size - EPSILON
    return selected, collections


@pytest.mark.parametrize("profile", PROFILE_CASES, ids=[case[0] for case in PROFILE_CASES])
@pytest.mark.parametrize("name,collections", LONG_CASES, ids=["unbroken", "multiword", "unicode", "many"])
def test_collection_and_box_names_fit_without_qr_or_code_collisions(
    renderer, label_box, profile, name, collections
):
    data, _ = renderer.render({**label_box, "name": name, "collection_names": collections}, profile[0])
    runs = text_runs(read_pdf(data).pages[0])
    assigned = 0
    for cell in label_cells(profile):
        selected, collection_runs = assert_cell_geometry(
            runs, cell, compact=profile[0].startswith("roll"), sheet=profile[3] == 14
        )
        assigned += len(selected)
        printed = " ".join(run.text for run in collection_runs)
        assert printed == unicodedata.normalize("NFC", printed)
        if len(collections) == 30 or collections == ["W" * 120]:
            assert printed.endswith("…"), "Truncated membership must be visible to the reader"
    assert assigned == len(runs), "Every text run belongs to its physical label cell"


def test_batch_collection_text_stays_inside_offset_cells_and_partial_sheet(renderer):
    boxes = sample_boxes(3)
    for label in boxes:
        label.update(name="W" * 120, collection_names=["W" * 120, "Garden"])
    pages = read_pdf(renderer.render_sheet(boxes, start_position=10, offset_x_mm=3, offset_y_mm=-3)[0]).pages
    assert len(pages) == 2
    for page_index, page in enumerate(pages):
        runs = text_runs(page)
        assigned = 0
        for index in range(len(boxes)):
            absolute = 9 + index
            if absolute // 10 != page_index:
                continue
            row, col = divmod(absolute % 10, 2)
            cell = (11.25 + col * 301.5 + 3 * mm, 612 - row * 144 + 3 * mm, 288, 144)
            selected, _ = assert_cell_geometry(runs, cell)
            assigned += len(selected)
        assert assigned == len(runs)


@pytest.mark.parametrize("dpi", [150, 203])
@pytest.mark.parametrize("layout", ["compact", "batch"])
def test_qr_codes_with_long_collections_decode_at_print_resolutions(renderer, tmp_path, dpi, layout):
    boxes = sample_boxes(1 if layout == "compact" else 11)
    for label in boxes:
        label.update(name="W" * 120, collection_names=["W" * 120, "Garden", "Moving supplies"])
    data = (
        renderer.render(boxes[0], "roll-62x29-mm-v1")[0]
        if layout == "compact"
        else renderer.render_sheet(boxes)[0]
    )
    path = tmp_path / "labels.pdf"
    path.write_bytes(data)
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", str(path), str(tmp_path / "page")],
        check=True,
        capture_output=True,
    )
    decoded = []
    for page in sorted(tmp_path.glob("page-*.png")):
        with Image.open(page) as image:
            decoded.extend(result.text for result in zxingcpp.read_barcodes(image))
    assert sorted(decoded) == sorted("boxen:v1:" + label["public_code"] for label in boxes)
