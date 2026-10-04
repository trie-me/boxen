import hashlib
import io
import json
import unicodedata
from pathlib import Path

import segno
from boxen.catalog.domain import BoxCode
from boxen.shared.errors import DomainError
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

PROFILES = [
    {
        "key": "roll-62x29-mm-v1",
        "version": 1,
        "display_name": "Compact roll · 62 × 29 mm",
        "width_mm": 62.0,
        "height_mm": 29.0,
    },
    {
        "key": "sheet-4x2-in-v1",
        "version": 1,
        "display_name": "Large label · 4 × 2 in",
        "width_mm": 101.6,
        "height_mm": 50.8,
    },
    {
        "key": "sheet-a4-2x7-v1",
        "version": 1,
        "display_name": "A4 sheet · 14 labels",
        "width_mm": 210.0,
        "height_mm": 297.0,
    },
]


class LabelRenderer:
    def __init__(self, assets: Path):
        self.font_hashes = []
        for name, filename in (
            ("BoxenSans", "NotoSans-Regular.ttf"),
            ("BoxenBold", "NotoSans-Bold.ttf"),
            ("BoxenMono", "NotoSansMono-Bold.ttf"),
        ):
            path = assets / "fonts" / filename
            pdfmetrics.registerFont(TTFont(name, str(path)))
            self.font_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())

    @staticmethod
    def lines(value: str, width: float, size: float, font: str = "BoxenBold") -> list[str]:
        lines = [""]
        for word in value.split():
            candidate = (lines[-1] + " " + word).strip()
            if pdfmetrics.stringWidth(candidate, font, size) <= width:
                lines[-1] = candidate
                continue
            if lines[-1]:
                lines.append("")
            # Only break inside an individual word when it cannot fit by itself.
            for char in word:
                if pdfmetrics.stringWidth(lines[-1] + char, font, size) > width and lines[-1]:
                    lines.append("")
                lines[-1] += char
        return [line.strip() for line in lines]

    @staticmethod
    def collection_names(box: dict) -> list[str]:
        names = {unicodedata.normalize("NFC", name.strip()) for name in box.get("collection_names", [])}
        return sorted(names - {""}, key=lambda name: (name.casefold(), name))

    @staticmethod
    def truncate(lines: list[str], count: int, width: float, size: float, font: str) -> list[str]:
        if len(lines) <= count:
            return lines
        lines = lines[:count]
        while lines[-1] and pdfmetrics.stringWidth(lines[-1] + "…", font, size) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
        return lines

    def draw_label(
        self,
        canvas: Canvas,
        box: dict,
        x: float,
        y: float,
        width: float,
        height: float,
        compact: bool = False,
        sheet: bool = False,
    ) -> None:
        margin = (2 if compact or sheet else 3) * mm
        qr_size = (25 if compact else 30 if sheet else 40) * mm
        gap = (2 if compact else 4) * mm
        qr = segno.make_qr(
            BoxCode.parse(box["public_code"]).qr_payload, error="q", mode="byte", boost_error=False
        )
        matrix = list(qr.matrix_iter(scale=1, border=4))
        module = qr_size / len(matrix)
        if module < 0.5 * mm:
            raise DomainError("label.too_small", "The QR allocation is below the minimum module size.", 500)
        qr_x, qr_y = x + margin, y + (height - qr_size) / 2
        canvas.setFillColorRGB(1, 1, 1)
        canvas.rect(x, y, width, height, stroke=0, fill=1)
        canvas.setFillColorRGB(0, 0, 0)
        for row_index, row in enumerate(matrix):
            for col_index, dark in enumerate(row):
                if dark:
                    canvas.rect(
                        qr_x + col_index * module,
                        qr_y + qr_size - (row_index + 1) * module,
                        module,
                        module,
                        stroke=0,
                        fill=1,
                    )
        text_x = qr_x + qr_size + gap
        text_width = x + width - margin - text_x
        nominal, minimum = (12, 9) if compact else (20, 12)
        code_size = 11 if compact else 15
        code_y = y + margin + (9 if compact else 13)
        collection_lines = []
        collection_top = code_y + pdfmetrics.getAscent("BoxenMono", code_size)
        names = self.collection_names(box)
        if names:
            collection_size, collection_minimum = (7.5, 7.5) if compact else (9.0, 8.0)
            collection_count = 1 if compact else 2
            collection_text = " · ".join(names)
            while (
                collection_size > collection_minimum
                and len(self.lines(collection_text, text_width, collection_size, "BoxenSans"))
                > collection_count
            ):
                collection_size -= 0.5
            collection_lines = self.truncate(
                self.lines(collection_text, text_width, collection_size, "BoxenSans"),
                collection_count,
                text_width,
                collection_size,
                "BoxenSans",
            )
            # Anchor collection text above the unchanged, full-size typeable code.
            collection_y = collection_top + 3 - pdfmetrics.getDescent("BoxenSans", collection_size)
            collection_top = (
                collection_y
                + (len(collection_lines) - 1) * collection_size * 1.18
                + pdfmetrics.getAscent("BoxenSans", collection_size)
            )
        value = unicodedata.normalize("NFC", box["name"].strip())
        size = float(nominal)
        while size > minimum:
            name_lines = self.lines(value, text_width, size)
            name_bottom = (
                y
                + height
                - margin
                - size
                - (min(2, len(name_lines)) - 1) * size * 1.18
                + pdfmetrics.getDescent("BoxenBold", size)
            )
            if len(name_lines) <= 2 and (not names or name_bottom >= collection_top + 3):
                break
            size -= 0.5
        lines = self.truncate(self.lines(value, text_width, size), 2, text_width, size, "BoxenBold")
        canvas.setFont("BoxenBold", size)
        name_top = y + height - margin - size
        for index, line in enumerate(lines):
            canvas.drawString(text_x, name_top - index * size * 1.18, line)
        if collection_lines:
            canvas.setFont("BoxenSans", collection_size)
            for index, line in enumerate(collection_lines):
                canvas.drawString(
                    text_x, collection_y + (len(collection_lines) - 1 - index) * collection_size * 1.18, line
                )
        canvas.setFont("BoxenMono", code_size)
        canvas.drawString(text_x, code_y, box["public_code"])
        canvas.setFont("BoxenSans", 6 if compact else 8)
        canvas.drawString(text_x, y + margin, "BOXEN")

    def render(self, box: dict, profile_key: str) -> tuple[bytes, str]:
        profile = next((p for p in PROFILES if p["key"] == profile_key), None)
        if not profile:
            raise DomainError("label.profile_invalid", "Choose an available label profile.")
        stream = io.BytesIO()
        canvas = Canvas(
            stream,
            pagesize=(profile["width_mm"] * mm, profile["height_mm"] * mm),
            invariant=1,
            pageCompression=1,
        )
        canvas.setTitle("Boxen label")
        canvas.setAuthor("Boxen")
        canvas.setCreator("Boxen label-v2 / " + profile_key)
        if profile_key == "sheet-a4-2x7-v1":
            for row in range(7):
                for col in range(2):
                    self.draw_label(
                        canvas,
                        box,
                        (4.65 + col * 101.6) * mm,
                        (15.15 + row * 38.1) * mm,
                        99.1 * mm,
                        38.1 * mm,
                        sheet=True,
                    )
        else:
            self.draw_label(
                canvas,
                box,
                0,
                0,
                profile["width_mm"] * mm,
                profile["height_mm"] * mm,
                compact=profile_key.startswith("roll"),
            )
        canvas.showPage()
        canvas.save()
        data = stream.getvalue()
        version = hashlib.sha256(
            json.dumps(
                [
                    box["public_code"],
                    box["name"],
                    box["version"],
                    self.collection_names(box),
                    profile_key,
                    "label-v2",
                    self.font_hashes,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return data, '"' + version + '"'

    def render_sheet(
        self,
        boxes: list[dict],
        start_position: int = 1,
        offset_x_mm: float = 0,
        offset_y_mm: float = 0,
    ) -> tuple[bytes, str]:
        """Letter 2 x 5 stock: 4 x 2 in, 0.1875 in gutter, row-major order.

        The first page may begin partway through a sheet. Positive offsets move
        the print right/down, without changing label or QR dimensions.
        """
        if not 1 <= len(boxes) <= 500:
            raise DomainError("label.count_invalid", "Choose between 1 and 500 labels per document.")
        if not 1 <= start_position <= 10 or not all(-3 <= n <= 3 for n in (offset_x_mm, offset_y_mm)):
            raise DomainError("label.layout_invalid", "Choose a valid starting position and alignment.")
        stream = io.BytesIO()
        canvas = Canvas(stream, pagesize=letter, invariant=1, pageCompression=1)
        canvas.setTitle("Boxen label print list")
        canvas.setAuthor("Boxen")
        canvas.setCreator("Boxen letter-4x2-10-v2")
        canvas.setViewerPreference("PrintScaling", "None")
        canvas.setViewerPreference("Duplex", "Simplex")
        for index, box in enumerate(boxes):
            position = start_position - 1 + index
            if index and position % 10 == 0:
                canvas.showPage()
            row, col = divmod(position % 10, 2)
            self.draw_label(
                canvas,
                box,
                (0.15625 + col * 4.1875) * 72 + offset_x_mm * mm,
                (8.5 - row * 2) * 72 - offset_y_mm * mm,
                4 * 72,
                2 * 72,
            )
        canvas.showPage()
        canvas.save()
        data = stream.getvalue()
        memberships = json.dumps(
            [self.collection_names(box) for box in boxes], ensure_ascii=False, separators=(",", ":")
        ).encode()
        return data, '"' + hashlib.sha256(data + memberships).hexdigest() + '"'
