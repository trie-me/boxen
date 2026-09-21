import hashlib
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from boxen.shared.errors import DomainError, require
from boxen.shared.values import markdown_value, text_value

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class BoxCode:
    value: str

    @staticmethod
    def from_payload(payload: str) -> "BoxCode":
        check = ALPHABET[hashlib.sha256(("BOXEN-BOX-CODE-V1:" + payload).encode("ascii")).digest()[0] & 31]
        raw = payload + check
        return BoxCode(f"BX-{raw[:4]}-{raw[4:]}")

    @staticmethod
    def generate() -> "BoxCode":
        value = secrets.randbits(35)
        return BoxCode.from_payload("".join(ALPHABET[(value >> shift) & 31] for shift in range(30, -1, -5)))

    @staticmethod
    def parse(raw: str) -> "BoxCode":
        if len(raw) > 64 or not raw.isascii():
            raise DomainError("box.code_invalid", "Enter a Boxen code such as BX-7K3M-R9QA.")
        compact = raw.upper().replace("-", "").replace(" ", "")
        compact = compact.translate(str.maketrans("OIL", "011"))
        if not re.fullmatch(r"BX[0-9A-HJKMNP-TV-Z]{8}", compact):
            raise DomainError("box.code_invalid", "The box code format is invalid.")
        expected = BoxCode.from_payload(compact[2:9])
        if expected.value.replace("-", "") != compact:
            raise DomainError(
                "box.code_checksum", "The box code check character does not match. Check the printed code."
            )
        return expected

    @property
    def qr_payload(self) -> str:
        return f"boxen:v1:{self.value}"


def resolve_payload(raw: str, origin: str) -> tuple[BoxCode, str]:
    if not 0 < len(raw) <= 512:
        raise DomainError("qr.invalid", "The code is empty or too long.")
    raw = raw.strip()
    if raw.startswith("boxen:"):
        pieces = raw.split(":", 2)
        if len(pieces) != 3:
            raise DomainError("qr.invalid", "This is not a complete Boxen label.")
        if pieces[1] != "v1":
            raise DomainError("qr.unsupported_version", "This Boxen label uses an unsupported version.")
        return BoxCode.parse(pieces[2]), "qr_payload"
    if "://" in raw:
        parsed, local = urlsplit(raw), urlsplit(origin)
        if (
            (parsed.scheme, parsed.netloc) != (local.scheme, local.netloc)
            or parsed.query
            or parsed.fragment
            or parsed.username
            or not re.fullmatch(r"/boxes/BX-[0-9A-Z]{4}-[0-9A-Z]{4}", parsed.path)
        ):
            raise DomainError("qr.invalid", "This URL is not a label from this Boxen host.")
        return BoxCode.parse(parsed.path.removeprefix("/boxes/")), "local_url"
    return BoxCode.parse(raw), "box_code"


@dataclass
class Box:
    name: str
    description_markdown: str = ""
    lifecycle: str = "active"

    def validate(self) -> None:
        self.name = text_value(self.name, 120, "Box name")
        markdown_value(self.description_markdown, 65536)
        require(self.lifecycle in {"active", "archived"}, "box.lifecycle_invalid", "Invalid box state.")

    @staticmethod
    def require_active(row: dict) -> None:
        require(
            row["lifecycle"] == "active",
            "box.archived",
            "Restore this archived box before changing its contents.",
        )
