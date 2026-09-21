import secrets
import time
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from boxen.shared.errors import DomainError


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def after(seconds: float, base: str | None = None) -> str:
    value = datetime.fromisoformat(base) if base else datetime.now(UTC)
    return (value + timedelta(seconds=seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_id() -> str:
    # RFC 9562 UUIDv7: 48-bit milliseconds, version, random payload, RFC variant.
    value = (int(time.time() * 1000) << 80) | (7 << 76) | (secrets.randbits(12) << 64)
    return str(uuid.UUID(int=value | (2 << 62) | secrets.randbits(62)))


def text_value(value: str, maximum: int, field: str, *, empty: bool = False) -> str:
    value = value.strip()
    if (
        (not value and not empty)
        or len(value) > maximum
        or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
    ):
        raise DomainError(
            "value.invalid",
            f"{field} must contain {'0' if empty else '1'}–{maximum} characters without control characters.",
        )
    return value


def markdown_value(value: str, maximum: int) -> str:
    try:
        valid = len(value.encode("utf-8")) <= maximum and "\x00" not in value
    except UnicodeError:
        valid = False
    if not valid:
        raise DomainError("markdown.invalid", f"Markdown must be valid UTF-8 and at most {maximum} bytes.")
    return value


def quantity_milli(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = Decimal(value)
        milli = number * 1000
        if (
            not number.is_finite()
            or not 0 < number <= Decimal("999999.999")
            or milli != milli.to_integral_value()
        ):
            raise ValueError
        return int(milli)
    except (ValueError, InvalidOperation, TypeError):
        raise DomainError(
            "quantity.invalid", "Use a positive quantity up to 999999.999, with at most three decimal places."
        ) from None


def quantity_text(value: int | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value) / 1000, "f").rstrip("0").rstrip(".") if value % 1000 else str(value // 1000)


def etag(kind: str, public_id: str, version: int) -> str:
    return f'"{kind}:{public_id}:v{version}"'


def check_etag(supplied: str | None, expected: str) -> None:
    if not supplied:
        raise DomainError("resource.precondition_required", "Reload the current resource before saving.", 428)
    if supplied != expected:
        raise DomainError(
            "resource.version_conflict",
            "This record changed in another session. Reload it before saving.",
            412,
            {"ETag": expected},
        )
