import hashlib
import io
import unicodedata
from pathlib import Path

import segno
from boxen.catalog.domain import BoxCode
from boxen.shared.errors import DomainError
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
    def lines(value: str, width: float, size: float) -> list[str]:
        lines = [""]
        for word in value.split():
            candidate = (lines[-1] + " " + word).strip()
            if pdfmetrics.stringWidth(candidate, "BoxenBold", size) <= width:
                lines[-1] = candidate
                continue
            if lines[-1]:
                lines.append("")
            # Only break inside an individual word when it cannot fit by itself.
            for char in word:
                if pdfmetrics.stringWidth(lines[-1] + char, "BoxenBold", size) > width and lines[-1]:
                    lines.append("")
                lines[-1] += char
        return [line.strip() for line in lines]

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
        value = unicodedata.normalize("NFC", box["name"].strip())
        size = float(nominal)
        while size > minimum and len(self.lines(value, text_width, size)) > 2:
            size -= 0.5
        lines = self.lines(value, text_width, size)
        if len(lines) > 2:
            lines = lines[:2]
            while lines[-1] and pdfmetrics.stringWidth(lines[-1] + "…", "BoxenBold", size) > text_width:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "…"
        canvas.setFont("BoxenBold", size)
        name_top = y + height - margin - size
        for index, line in enumerate(lines):
            canvas.drawString(text_x, name_top - index * size * 1.18, line)
        code_size = 11 if compact else 15
        canvas.setFont("BoxenMono", code_size)
        canvas.drawString(text_x, y + margin + (9 if compact else 13), box["public_code"])
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
        canvas.setCreator("Boxen label-v1 / " + profile_key)
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
            (
                box["public_code"]
                + box["name"]
                + str(box["version"])
                + profile_key
                + "label-v1"
                + "".join(self.font_hashes)
            ).encode()
        ).hexdigest()
        return data, '"' + version + '"'
