"""Inspect real PDFs in memory; browser rendering and visual QA are separate checks."""

import io
import re
import unicodedata
from dataclasses import dataclass

import pytest
from boxen.catalog.domain import BoxCode
from boxen.labeling.infrastructure.pdf import PROFILES, LabelRenderer
from boxen.platform.config import Settings
from pypdf import PdfReader
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics

PROFILE_CASES = [
    ("roll-62x29-mm-v1", 62.0, 29.0, 1),
    ("sheet-4x2-in-v1", 101.6, 50.8, 1),
    ("sheet-a4-2x7-v1", 210.0, 297.0, 14),
]
FONT_NAMES = {
    "NotoSans-Bold": "BoxenBold",
    "NotoSansMono-Bold": "BoxenMono",
    "NotoSans-Regular": "BoxenSans",
}
EPSILON = 0.001  # PDF coordinates are rounded to a few decimal places, in points.


@pytest.fixture(scope="module")
def renderer():
    return LabelRenderer(Settings().assets)


@pytest.fixture(params=PROFILE_CASES, ids=[case[0] for case in PROFILE_CASES])
def profile(request):
    return request.param


@pytest.fixture
def box():
    return {"public_code": BoxCode.from_payload("7K3MR9Q").value, "name": "Workshop tools", "version": 1}


@dataclass(frozen=True)
class TextRun:
    text: str
    x: float
    y: float
    font: str
    size: float

    @property
    def right(self):
        return self.x + pdfmetrics.stringWidth(self.text, self.font, self.size)

    @property
    def top(self):
        return self.y + pdfmetrics.getAscent(self.font, self.size)

    @property
    def bottom(self):
        return self.y + pdfmetrics.getDescent(self.font, self.size)


def text_runs(page):
    runs = []

    def visit(text, cm, tm, font, size):
        if not text.strip():
            return
        # These labels use unrotated, untranslated text. Fail explicitly if that changes.
        assert cm == [1, 0, 0, 1, 0, 0]
        assert tm[:4] == [1, 0, 0, 1]
        face = str(font["/BaseFont"]).split("+")[-1].lstrip("/")
        assert face in FONT_NAMES
        descriptor = font["/FontDescriptor"].get_object()
        assert descriptor["/FontFile2"].get_object().get_data(), "Label font must be embedded"
        assert font["/ToUnicode"].get_object().get_data(), "Label text must remain extractable"
        runs.append(TextRun(text.rstrip("\n"), tm[4], tm[5], FONT_NAMES[face], size))

    page.extract_text(visitor_text=visit)
    return runs


def label_cells(profile):
    _, width, height, count = profile
    if count == 14:
        return [
            ((4.65 + col * 101.6) * mm, (15.15 + row * 38.1) * mm, 99.1 * mm, 38.1 * mm)
            for row in range(7)
            for col in range(2)
        ]
    return [(0, 0, width * mm, height * mm)]


def read_label(data):
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    return page, text_runs(page)


def test_layout_cases_cover_every_builtin_profile():
    assert {case[0] for case in PROFILE_CASES} == {profile["key"] for profile in PROFILES}


def test_pdf_contains_name_and_code_on_every_label(renderer, box, profile):
    key, width, height, count = profile
    data, _ = renderer.render(box, key)
    page, runs = read_label(data)
    assert float(page.mediabox.width) == pytest.approx(width * mm)
    assert float(page.mediabox.height) == pytest.approx(height * mm)
    assert sum(run.text == box["public_code"] for run in runs) == count
    assert sum(run.text == "BOXEN" for run in runs) == count
    assigned = 0
    for x, y, cell_width, cell_height in label_cells(profile):
        cell = [run for run in runs if x <= run.x < x + cell_width and y <= run.y < y + cell_height]
        assigned += len(cell)
        assert " ".join(run.text for run in cell if run.font == "BoxenBold") == box["name"]
        assert [run.text for run in cell if run.font == "BoxenMono"] == [box["public_code"]]
        assert [run.text for run in cell if run.font == "BoxenSans"] == ["BOXEN"]
    assert assigned == len(runs), "No text may fall outside its label cell"


@pytest.mark.parametrize(
    "name",
    [
        "Workshop / precision tools and adapters",
        ("Workshop tools and spare parts " * 4)[:120],
        "W" * 120,
        ("gypq " * 24).strip(),
        "Ångström café – pièces détachées",
    ],
    ids=["multiword", "maximum-multiword", "unbroken-word", "descenders", "accented"],
)
def test_long_names_fit_without_qr_or_code_collisions(renderer, box, profile, name):
    assert len(name) <= 120  # Exercise names accepted by the box domain.
    box = {**box, "name": name}
    key, _, _, count = profile
    _, runs = read_label(renderer.render(box, key)[0])
    compact = key.startswith("roll")
    margin = (2 if compact or count == 14 else 3) * mm
    qr_size = (25 if compact else 30 if count == 14 else 40) * mm
    gap = (2 if compact else 4) * mm
    minimum, nominal = (9, 12) if compact else (12, 20)
    assigned = 0
    for x, y, width, height in label_cells(profile):
        cell = [run for run in runs if x <= run.x < x + width and y <= run.y < y + height]
        assigned += len(cell)
        names = [run for run in cell if run.font == "BoxenBold"]
        codes = [run for run in cell if run.font == "BoxenMono"]
        branding = [run for run in cell if run.font == "BoxenSans"]
        assert 1 <= len(names) <= 2
        assert len(codes) == len(branding) == 1
        assert codes[0].text == box["public_code"]
        for run in cell:
            # The QR's allocation includes its quiet zone, not just its dark modules.
            assert run.x >= x + margin + qr_size + gap - EPSILON
            assert run.right <= x + width - margin + EPSILON, run
            assert run.bottom >= y - EPSILON, run
            assert run.top <= y + height + EPSILON, run
        assert all(minimum <= run.size <= nominal for run in names)
        assert len({run.size for run in names}) == 1
        for upper, lower in zip(names, names[1:]):
            # Global font ascender/descender boxes overlap at normal line spacing;
            # require a full em between baselines rather than treating those as ink.
            assert upper.y - lower.y >= upper.size - EPSILON
        assert min(run.bottom for run in names) > codes[0].top, "Name overlaps typeable code"
        # BOXEN is all capitals, so cap height is the relevant upper ink bound.
        face = pdfmetrics.getFont(branding[0].font).face
        branding_top = branding[0].y + face.capHeight * branding[0].size / 1000
        assert branding_top < codes[0].bottom, "Branding overlaps typeable code"
        displayed = "".join(run.text for run in names)
        original = "".join(unicodedata.normalize("NFC", name).split())
        if displayed.endswith("…"):
            assert names[-1].size == minimum
            assert original.startswith("".join(displayed[:-1].split()))
        else:
            assert "".join(displayed.split()) == original
        if name == "W" * 120:
            assert len(names) == 2 and displayed.endswith("…")
    assert assigned == len(runs)


def test_pdf_normalizes_name_to_nfc(renderer, box, profile):
    box = {**box, "name": "  Cafe\u0301 tools  "}
    _, runs = read_label(renderer.render(box, profile[0])[0])
    for x, y, width, height in label_cells(profile):
        names = [
            run.text
            for run in runs
            if run.font == "BoxenBold" and x <= run.x < x + width and y <= run.y < y + height
        ]
        assert " ".join(names) == "Café tools"


def test_pdf_bytes_and_etag_are_deterministic(renderer, box, profile):
    first = renderer.render(box, profile[0])
    assert renderer.render(box, profile[0]) == first
    assert re.fullmatch(r'"[0-9a-f]{64}"', first[1])


def test_renaming_changes_pdf_text_and_etag_even_without_version_change(renderer, box, profile):
    before, old_etag = renderer.render(box, profile[0])
    renamed = {**box, "name": "Garden"}
    after, new_etag = renderer.render(renamed, profile[0])
    assert new_etag != old_etag
    assert after != before
    _, runs = read_label(after)
    assert [run.text for run in runs if run.font == "BoxenBold"] == ["Garden"] * profile[3]
    assert [run.text for run in runs if run.font == "BoxenMono"] == [box["public_code"]] * profile[3]


def test_profile_and_box_version_are_part_of_etag(renderer, box):
    tags = {renderer.render(box, key)[1] for key, *_ in PROFILE_CASES}
    assert len(tags) == len(PROFILE_CASES)
    for key, *_ in PROFILE_CASES:
        assert renderer.render({**box, "version": box["version"] + 1}, key)[1] not in tags
