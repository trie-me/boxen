import re
from dataclasses import dataclass

from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, now, text_value

ROLES = {"viewer": 0, "editor": 1, "owner": 2}
ANONYMOUS_USER_ID = "00000000-0000-4000-8000-000000000001"
# Outside the accepted username syntax, so existing local accounts cannot collide.
ANONYMOUS_USERNAME = "@boxen-anonymous"


def username_key(value: str) -> str:
    if not re.fullmatch(r"[\w.\-]{3,64}", value, flags=re.UNICODE):
        raise DomainError(
            "user.username_invalid", "Use 3–64 letters, numbers, underscores, dots, or hyphens."
        )
    return value.casefold()


def validate_password(value: str) -> None:
    if len(value) < 12 or len(value.encode("utf-8")) > 1024:
        raise DomainError("user.password_invalid", "Use at least 12 characters and no more than 1024 bytes.")
    if value.casefold() in {
        "passwordpassword",
        "password1234",
        "123456789012",
        "qwertyuiop12",
        "letmeinletmein",
    }:
        raise DomainError("user.password_common", "Choose a less common password.")


@dataclass(frozen=True)
class Actor:
    user: dict
    session_hash: str
    authenticated_at: str
    request_id: str

    @property
    def anonymous(self) -> bool:
        return self.user["id"] == ANONYMOUS_USER_ID

    def authorize(self, minimum: str = "viewer", recent: bool = False) -> None:
        require(
            self.user["status"] == "active"
            and ROLES.get(self.user["role"], -1) >= ROLES[minimum]
            and not (self.anonymous and (minimum == "owner" or recent)),
            "auth.forbidden",
            "Your account cannot perform this action.",
            403,
        )
        if recent:
            require(
                after(900, self.authenticated_at) > now(),
                "auth.reauthentication_required",
                "Sign in again before this sensitive action.",
                403,
            )


def validate_user(body: dict) -> None:
    for field in ("username", "display_name", "password"):
        if field not in body:
            continue
        try:
            if field == "username":
                username_key(body[field])
            elif field == "display_name":
                text_value(body[field], 120, "Display name")
            else:
                validate_password(body[field])
        except DomainError as error:
            error.errors = [{"path": f"/{field}", "code": error.code, "message": error.detail}]
            raise
