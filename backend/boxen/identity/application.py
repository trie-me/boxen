import base64
import hashlib
import hmac
import json
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
PEPPER_PREFIX = "$boxen-pepper-v1$"
USER_FIELDS = ("id", "username", "display_name", "role", "status", "version", "created_at", "updated_at")


def user_view(row: dict) -> dict:
    return {
        **{key: row[key] for key in USER_FIELDS},
        "is_system_admin": bool(row.get("is_system_admin", False)),
        "local_password": not row["password_hash"].startswith("!"),
    }


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
        self.pepper = settings.password_pepper()

    def password_material(self, password: str) -> str:
        return base64.b64encode(hmac.digest(self.pepper, password.encode("utf-8"), "sha256")).decode("ascii")

    def hash_password(self, password: str) -> str:
        return PEPPER_PREFIX + HASHER.hash(self.password_material(password))

    def verify_password(self, encoded: str, password: str) -> bool:
        local_password = not encoded.startswith("!")
        if encoded.startswith(PEPPER_PREFIX):
            encoded = encoded.removeprefix(PEPPER_PREFIX)
            password = self.password_material(password)
        elif encoded.startswith("!"):
            # OIDC-only and unknown identities still perform one expensive verification.
            encoded = DUMMY_HASH
        try:
            valid = HASHER.verify(encoded, password)
            return bool(local_password and valid)
        except (VerificationError, InvalidHashError):
            return False

    def validate_password_pepper(self, repo) -> None:
        expected = repo.setting("password_pepper_fingerprint")
        require(
            expected is not None and hmac.compare_digest(expected, hashlib.sha256(self.pepper).hexdigest()),
            "auth.pepper_invalid",
            "Password pepper does not match this installation. Restore its original file.",
            503,
        )

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
        return self.start_session(
            repo, {**user, "role": self.settings.anonymous_access}, request_id, "anonymous"
        )

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

    def start_session(self, repo, user: dict, request_id: str, method: str = "password") -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        at = now()
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        repo.insert(
            "sessions",
            {
                "id": new_id(),
                "method": method,
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
        valid = self.verify_password(user["password_hash"] if user else DUMMY_HASH, body["password"])
        if not valid or not user or user["status"] != "active":
            self.rate_limit(repo, key, consume=True)
            repo.audit(None, "auth.login_failed", "session", "redacted", request_id, {"method": "password"})
            return DomainError("auth.invalid_credentials", "Sign-in details were not accepted.", 401)
        repo.set_setting(key, {"count": 0, "until": after(900)})
        if not user["password_hash"].startswith(PEPPER_PREFIX) or HASHER.check_needs_rehash(
            user["password_hash"].removeprefix(PEPPER_PREFIX)
        ):
            repo.update("users", {"password_hash": self.hash_password(body["password"])}, id=user["id"])
        repo.audit(user["id"], "auth.login", "user", user["id"], request_id, {"method": "password"})
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
        user = self.create_user(repo, {**body, "role": "owner"}, None, request_id, system_admin=True)
        repo.set_setting("setup_token_hash", None)
        repo.audit(user["id"], "setup.completed", "installation", "local", request_id)
        return self.start_session(repo, user, request_id)

    def create_user(
        self, repo, body: dict, actor: Actor | None, request_id: str, *, system_admin: bool = False
    ) -> dict:
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
            "password_hash": self.hash_password(body["password"]),
            "is_system_admin": int(system_admin),
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
        if row["is_system_admin"]:
            require(
                body.get("role", "owner") == "owner" and body.get("status", "active") == "active",
                "user.system_admin_protected",
                "The core system administrator must remain an active owner.",
            )
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
            changes["password_hash"] = self.hash_password(body["password"])
        repo.update("users", changes, id=user_id)
        repo.audit(
            actor.user["id"], "user.updated", "user", user_id, actor.request_id, {"fields": sorted(body)}
        )
        return repo.one("users", id=user_id)

    def change_password(self, repo, body: dict, actor: Actor, client: str):
        require(not actor.anonymous, "auth.forbidden", "Anonymous access has no password.", 403)
        key = self.rate_key(actor.user["username"], client, "password")
        self.rate_limit(repo, key)
        valid = self.verify_password(actor.user["password_hash"], body["current_password"])
        if not valid:
            self.rate_limit(repo, key, consume=True)
            return DomainError("auth.invalid_credentials", "The current password was not accepted.", 401)
        validate_password(body["new_password"])
        for session in repo.find("sessions", user_id=actor.user["id"]):
            repo.update("sessions", {"revoked_at": now()}, token_hash=session["token_hash"])
        repo.update(
            "users",
            {
                "password_hash": self.hash_password(body["new_password"]),
                "credential_version": actor.user["credential_version"] + 1,
                "version": actor.user["version"] + 1,
                "updated_at": now(),
            },
            id=actor.user["id"],
        )
        repo.audit(actor.user["id"], "user.password_changed", "user", actor.user["id"], actor.request_id)
        return self.start_session(repo, repo.one("users", id=actor.user["id"]), actor.request_id)

    def list_sessions(self, repo, actor: Actor, user_id: str | None = None) -> dict:
        actor.authorize("owner")
        if user_id is not None:
            require(repo.one("users", id=user_id) is not None, "user.not_found", "User not found.", 404)
        rows = repo.rows(
            "SELECT sessions.*, users.username, users.status AS user_status, "
            "users.credential_version AS user_credential_version FROM sessions "
            "JOIN users ON users.id = sessions.user_id WHERE (:user_id IS NULL OR sessions.user_id = :user_id) "
            "ORDER BY sessions.created_at DESC, sessions.id DESC LIMIT 500",
            {"user_id": user_id},
        )
        at = now()
        return {
            "items": [
                {
                    **{
                        key: row[key]
                        for key in (
                            "id",
                            "user_id",
                            "username",
                            "method",
                            "created_at",
                            "last_seen_at",
                            "expires_at",
                            "revoked_at",
                        )
                    },
                    "active": bool(
                        row["revoked_at"] is None
                        and row["expires_at"] > at
                        and after(12 * 3600, row["last_seen_at"]) > at
                        and row["user_status"] == "active"
                        and row["credential_version"] == row["user_credential_version"]
                        and (row["user_id"] != ANONYMOUS_USER_ID or self.settings.anonymous_access != "off")
                    ),
                    "current": row["token_hash"] == actor.session_hash,
                }
                for row in rows
            ]
        }

    def revoke_session(self, repo, actor: Actor, session_id: str) -> None:
        actor.authorize("owner", recent=True)
        session = repo.one("sessions", id=session_id)
        require(session is not None, "session.not_found", "Sign-in session not found.", 404)
        if session["revoked_at"] is None:
            repo.update("sessions", {"revoked_at": now()}, id=session_id)
        repo.audit(actor.user["id"], "auth.session_revoked", "session", session_id, actor.request_id)

    def revoke_user_sessions(self, repo, actor: Actor, user_id: str) -> dict:
        actor.authorize("owner", recent=True)
        require(repo.one("users", id=user_id) is not None, "user.not_found", "User not found.", 404)
        sessions = repo.find("sessions", user_id=user_id, revoked_at=None)
        repo.update("sessions", {"revoked_at": now()}, user_id=user_id, revoked_at=None)
        repo.audit(actor.user["id"], "auth.user_sessions_revoked", "user", user_id, actor.request_id)
        return {"revoked": len(sessions)}

    def sign_in_events(self, repo, actor: Actor, limit: int = 100) -> dict:
        actor.authorize("owner")
        require(1 <= limit <= 500, "request.invalid", "Choose an event limit between 1 and 500.")
        rows = repo.rows(
            "SELECT audit_log.*, users.username FROM audit_log LEFT JOIN users "
            "ON users.id = audit_log.actor_user_id WHERE audit_log.action LIKE 'auth.%' "
            "OR audit_log.action IN ('setup.completed', 'user.password_changed', 'user.password_reset') "
            "ORDER BY audit_log.sequence DESC LIMIT :limit",
            {"limit": limit},
        )
        return {
            "items": [
                {
                    "id": row["sequence"],
                    "occurred_at": row["occurred_at"],
                    "user_id": row["actor_user_id"],
                    "username": row["username"],
                    "action": row["action"],
                    "method": json.loads(row["metadata_json"]).get("method"),
                }
                for row in rows
            ]
        }

    def reset_admin_password(self, repo, password: str, request_id: str) -> dict:
        """Offline host-authorized recovery, called only while holding the exclusive runtime lock."""
        validate_password(password)
        user = repo.one("users", is_system_admin=1)
        require(
            user is not None, "user.not_found", "Complete initial administrator setup before recovery.", 404
        )
        at = now()
        repo.update("sessions", {"revoked_at": at}, user_id=user["id"], revoked_at=None)
        repo.update(
            "users",
            {
                "password_hash": self.hash_password(password),
                "credential_version": user["credential_version"] + 1,
                "version": user["version"] + 1,
                "updated_at": at,
            },
            id=user["id"],
        )
        repo.audit(user["id"], "user.password_reset", "user", user["id"], request_id, {"method": "offline"})
        return user_view(repo.one("users", id=user["id"]))
