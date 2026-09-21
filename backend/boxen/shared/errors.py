from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainError(Exception):
    code: str
    detail: str
    status: int = 422
    headers: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        return self.detail


def require(condition: bool, code: str, detail: str, status: int = 409) -> None:
    if not condition:
        raise DomainError(code, detail, status)
