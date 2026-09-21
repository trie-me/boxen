import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from boxen.identity.domain import (
    ANONYMOUS_USER_ID,
    ANONYMOUS_USERNAME,
    Actor,
    username_key,
    validate_password,
    validate_user,
)
from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, check_etag, etag, new_id, now

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(24))
USER_FIELDS = ("id", "username", "display_name", "role", "status", "version", "created_at", "updated_at")


def user_view(row: dict) -> dict:
    return {key: row[key] for key in USER_FIELDS}


def capabilities(role: str) -> list[str]:
    result = ["box.read", "search", "scan"]
    if role in {"editor", "owner"}:
        result += ["box.edit", "image.upload", "inventory.edit", "observation.review", "label.render"]
    if role == "owner":
        result += ["users.manage", "system.manage", "backup.manage", "box.purge"]
    return result


class Identity:
    def __init__(self, settings):
        self.settings = settings
        self.secret = settings.secret()

    def local_users(self, repo) -> list[dict]:
        return [user for user in repo.find("users") if user["id"] != ANONYMOUS_USER_ID]

    def start_anonymous_session(self, repo, request_id: str) -> tuple[dict, str]:
        require(self.settings.anonymous_access != "off", "auth.required", "Sign in to continue.", 401)
        user = repo.one("users", id=ANONYMOUS_USER_ID)
        if user is None:
            at = now()
            user = {
                "id": ANONYMOUS_USER_ID,
                "username": ANONYMOUS_USERNAME,
                "username_key": ANONYMOUS_USERNAME,
                "display_name": "Anonymous",
                "role": "viewer",
                "password_hash": "!anonymous-login-disabled",
                "credential_version": 1,
                "status": "active",
                "version": 1,
                "created_at": at,
                "updated_at": at,
                "disabled_at": None,
            }
            repo.insert("users", user)
        # The row supports foreign keys; configuration alone grants anonymous roles.
        return self.start_session(repo, {**user, "role": self.settings.anonymous_access}, request_id)

    def csrf(self, token: str) -> str:
        return (
            base64.urlsafe_b64encode(hmac.digest(self.secret, b"csrf:" + token.encode(), "sha256"))
            .decode()
            .rstrip("=")
        )

    def authenticate(self, repo, token: str | None, request_id: str, touch: bool = True) -> Actor:
        if not token or len(token) > 256:
            raise DomainError("auth.required", "Sign in to continue.", 401)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session = repo.one("sessions", token_hash=token_hash)
        user = repo.one("users", id=session["user_id"]) if session else None
        valid = (
            session
            and user
            and not session["revoked_at"]
            and session["expires_at"] > now()
            and after(12 * 3600, session["last_seen_at"]) > now()
            and user["status"] == "active"
            and session["credential_version"] == user["credential_version"]
            and (user["id"] != ANONYMOUS_USER_ID or self.settings.anonymous_access != "off")
        )
        if not valid:
            raise DomainError("auth.required", "Your session expired. Sign in again.", 401)
        if touch and after(60, session["last_seen_at"]) < now():
            repo.update("sessions", {"last_seen_at": now()}, token_hash=token_hash)
        assert user is not None
        if user["id"] == ANONYMOUS_USER_ID:
            user = {**user, "role": self.settings.anonymous_access}
        return Actor(user, token_hash, session["created_at"], request_id)

    def session_view(self, repo, actor: Actor, token: str) -> dict:
        session = repo.one("sessions", token_hash=actor.session_hash)
        return {
            "anonymous": actor.anonymous,
            "user": user_view(actor.user),
            "csrf_token": self.csrf(token),
            "expires_at": session["expires_at"],
            "capabilities": capabilities(actor.user["role"]),
        }

    def start_session(self, repo, user: dict, request_id: str) -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        at = now()
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        repo.insert(
            "sessions",
            {
                "token_hash": session_hash,
                "user_id": user["id"],
                "credential_version": user["credential_version"],
                "csrf_secret_hash": hashlib.sha256(self.csrf(token).encode()).hexdigest(),
                "created_at": at,
                "last_seen_at": at,
                "expires_at": after(7 * 86400, at),
            },
        )
        return self.session_view(repo, Actor(user, session_hash, at, request_id), token), token

    def rate_key(self, username: str, client: str, purpose: str = "login") -> str:
        digest = hmac.digest(
            self.secret, (purpose + ":" + username.casefold() + ":" + client).encode(), "sha256"
        ).hex()
        return f"rate:{purpose}:{digest}"

    def rate_limit(self, repo, key: str, maximum: int = 5, window: int = 900, consume: bool = False) -> dict:
        state = repo.setting(key, {"count": 0, "until": after(window)})
        if state["until"] <= now():
            state = {"count": 0, "until": after(window)}
        if state["count"] >= maximum:
            raise DomainError(
                "auth.rate_limited", "Too many attempts. Try again later.", 429, {"Retry-After": str(window)}
            )
        if consume:
            state["count"] += 1
            repo.set_setting(key, state)
        return state

    def login(self, repo, body: dict, client: str, request_id: str):
        key = self.rate_key(body["username"], client)
        self.rate_limit(repo, key)
        self.rate_limit(repo, self.rate_key("all", client, "login-ip"), maximum=30, consume=True)
        user = repo.one("users", username_key=body["username"].casefold())
        if user and user["id"] == ANONYMOUS_USER_ID:
            user = None
        try:
            valid: bool = HASHER.verify(user["password_hash"] if user else DUMMY_HASH, body["password"])
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not user or user["status"] != "active":
            self.rate_limit(repo, key, consume=True)
            repo.audit(None, "auth.login_failed", "session", "redacted", request_id)
            return DomainError("auth.invalid_credentials", "Sign-in details were not accepted.", 401)
        repo.set_setting(key, {"count": 0, "until": after(900)})
        if HASHER.check_needs_rehash(user["password_hash"]):
            repo.update("users", {"password_hash": HASHER.hash(body["password"])}, id=user["id"])
        repo.audit(user["id"], "auth.login", "user", user["id"], request_id)
        return self.start_session(repo, user, request_id)

    def setup(self, repo, body: dict, setup_token: str, client: str, request_id: str):
        require(not self.local_users(repo), "setup.closed", "This installation already has an owner.")
        key = self.rate_key("setup", client, "setup")
        self.rate_limit(repo, key)
        expected = repo.setting("setup_token_hash", "")
        if not expected or not hmac.compare_digest(
            hashlib.sha256(setup_token.encode()).hexdigest(), expected
        ):
            self.rate_limit(repo, key, consume=True)
            repo.audit(None, "setup.denied", "installation", "local", request_id)
            return DomainError("setup.token_invalid", "The host setup token was not accepted.", 403)
        user = self.create_user(repo, {**body, "role": "owner"}, None, request_id)
        repo.set_setting("setup_token_hash", None)
        repo.audit(user["id"], "setup.completed", "installation", "local", request_id)
        return self.start_session(repo, user, request_id)

    def create_user(self, repo, body: dict, actor: Actor | None, request_id: str) -> dict:
        if actor:
            actor.authorize("owner", recent=True)
        require(
            body["username"].casefold() != ANONYMOUS_USERNAME,
            "user.reserved",
            "This identity is reserved for anonymous access.",
        )
        validate_user(body)
        key = username_key(body["username"])
        require(
            repo.one("users", username_key=key) is None, "user.username_taken", "Choose a different username."
        )
        at = now()
        row = {
            "id": new_id(),
            "username": body["username"],
            "username_key": key,
            "display_name": body["display_name"].strip(),
            "role": body["role"],
            "password_hash": HASHER.hash(body["password"]),
            "credential_version": 1,
            "status": "active",
            "version": 1,
            "created_at": at,
            "updated_at": at,
            "disabled_at": None,
        }
        repo.insert("users", row)
        repo.audit(actor.user["id"] if actor else row["id"], "user.created", "user", row["id"], request_id)
        return row

    def update_user(
        self, repo, body: dict, user_id: str, actor: Actor, supplied_etag: str | None, own: bool = False
    ) -> dict:
        actor.authorize("viewer" if own else "owner", recent=not own)
        require(
            user_id != ANONYMOUS_USER_ID,
            "auth.forbidden",
            "The anonymous identity cannot be changed.",
            403,
        )
        row = repo.one("users", id=user_id)
        require(row is not None, "user.not_found", "User not found.", 404)
        check_etag(supplied_etag, etag("user", row["id"], row["version"]))
        validate_user(body)
        if (
            row["role"] == "owner"
            and row["status"] == "active"
            and (body.get("role", "owner") != "owner" or body.get("status", "active") != "active")
        ):
            require(
                len(repo.find("users", role="owner", status="active")) > 1,
                "user.last_owner",
                "At least one active owner must remain.",
            )
        changes = {k: v for k, v in body.items() if k in {"display_name", "role", "status"}}
        changes.update(version=row["version"] + 1, updated_at=now())
        if "status" in body:
            changes["disabled_at"] = now() if body["status"] == "disabled" else None
        if any(k in body for k in ("password", "role", "status")):
            changes["credential_version"] = row["credential_version"] + 1
            for session in repo.find("sessions", user_id=user_id):
                repo.update("sessions", {"revoked_at": now()}, token_hash=session["token_hash"])
        if "password" in body:
            changes["password_hash"] = HASHER.hash(body["password"])
        repo.update("users", changes, id=user_id)
        repo.audit(
            actor.user["id"], "user.updated", "user", user_id, actor.request_id, {"fields": sorted(body)}
        )
        return repo.one("users", id=user_id)

    def change_password(self, repo, body: dict, actor: Actor, client: str):
        require(not actor.anonymous, "auth.forbidden", "Anonymous access has no password.", 403)
        key = self.rate_key(actor.user["username"], client, "password")
        self.rate_limit(repo, key)
        try:
            valid: bool = HASHER.verify(actor.user["password_hash"], body["current_password"])
        except VerificationError:
            valid = False
        if not valid:
            self.rate_limit(repo, key, consume=True)
            return DomainError("auth.invalid_credentials", "The current password was not accepted.", 401)
        validate_password(body["new_password"])
        for session in repo.find("sessions", user_id=actor.user["id"]):
            repo.update("sessions", {"revoked_at": now()}, token_hash=session["token_hash"])
        repo.update(
            "users",
            {
                "password_hash": HASHER.hash(body["new_password"]),
                "credential_version": actor.user["credential_version"] + 1,
                "version": actor.user["version"] + 1,
                "updated_at": now(),
            },
            id=actor.user["id"],
        )
        repo.audit(actor.user["id"], "user.password_changed", "user", actor.user["id"], actor.request_id)
        return self.start_session(repo, repo.one("users", id=actor.user["id"]), actor.request_id)
