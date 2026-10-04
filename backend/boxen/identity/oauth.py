"""OIDC sign-in with explicit local identity bindings and transient provider tokens."""

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
import jwt
from boxen.identity.domain import ANONYMOUS_USER_ID, Actor
from boxen.shared.errors import DomainError, require
from boxen.shared.values import after, new_id, now
from pydantic import BaseModel, ConfigDict, Field, ValidationError

TRANSACTION_SECONDS = 300
MAX_RESPONSE_BYTES = 256 * 1024
SIGNING_ALGORITHMS = {"RS256", "ES256"}
IDENTITY_FIELDS = ("id", "user_id", "provider_id", "issuer", "subject", "created_at")


def https_url(value: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError("OIDC URL must be a string.")
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and "\\" not in value
            and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("OIDC URLs must use HTTPS without credentials, query, or fragment.")
    return value


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    issuer: str = Field(min_length=1, max_length=2048)
    client_id: str = Field(min_length=1, max_length=255)
    client_secret_file: str | None = None
    enabled: bool = True


class ProviderFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    providers: list[Provider] = Field(max_length=20)


def load_providers(path: Path | None) -> dict[str, Provider]:
    if path is None:
        return {}
    try:
        if path.stat().st_size > 65536:
            raise ValueError("Provider configuration is too large.")
        config = ProviderFile.model_validate_json(path.read_bytes())
        providers: dict[str, Provider] = {}
        clients: set[tuple[str, str]] = set()
        for provider in config.providers:
            https_url(provider.issuer)
            if provider.id in providers:
                raise ValueError("Provider IDs must be unique.")
            if (provider.issuer, provider.client_id) in clients:
                raise ValueError("An issuer and client pair must be configured only once.")
            clients.add((provider.issuer, provider.client_id))
            if any(ord(char) < 32 or ord(char) == 127 for char in provider.label + provider.client_id):
                raise ValueError("Provider labels and client IDs must not contain control characters.")
            if provider.client_secret_file is not None:
                secret_path = Path(provider.client_secret_file)
                if not secret_path.is_absolute():
                    secret_path = path.parent / secret_path
                provider = provider.model_copy(update={"client_secret_file": str(secret_path.resolve())})
                if provider.enabled:
                    read_client_secret(provider)
            providers[provider.id] = provider
        return providers
    except (OSError, ValueError, ValidationError) as error:
        raise RuntimeError(
            "OIDC provider configuration is invalid; check the host configuration file."
        ) from error


def read_client_secret(provider: Provider) -> str | None:
    if provider.client_secret_file is None:
        return None
    path = Path(provider.client_secret_file)
    if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 16384:
        raise ValueError("OIDC client secret file must be private and contain a bounded secret.")
    secret = path.read_text().rstrip("\r\n")
    if not secret or any(ord(char) < 32 or ord(char) == 127 for char in secret):
        raise ValueError("OIDC client secret is invalid.")
    return secret


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OIDC:
    def __init__(self, settings, identity, database, transport: httpx.BaseTransport | None = None):
        self.settings, self.identity, self.database = settings, identity, database
        self.providers = load_providers(settings.oauth_providers_file)
        # Only tests explicitly inject a transport; HTTPS verification remains enabled in production.
        self.transport = transport

    def provider(self, provider_id: str) -> Provider:
        provider = self.providers.get(provider_id)
        require(
            provider is not None and provider.enabled,
            "auth.provider_unavailable",
            "Sign-in provider is unavailable.",
            404,
        )
        assert provider is not None
        return provider

    def redirect_uri(self, provider_id: str) -> str:
        return f"{self.settings.origin}/api/v1/auth/oidc/{provider_id}/callback"

    def public_providers(self) -> list[dict]:
        return [{"id": p.id, "label": p.label} for p in self.providers.values() if p.enabled]

    def provider_status(self, actor: Actor) -> list[dict]:
        actor.authorize("owner")
        return [
            {
                "id": p.id,
                "label": p.label,
                "issuer": p.issuer,
                "client_id": p.client_id,
                "configured": p.enabled,
                "redirect_uri": self.redirect_uri(p.id),
            }
            for p in self.providers.values()
        ]

    def _json(self, url: str, *, data: dict | None = None, auth: httpx.BasicAuth | None = None) -> dict:
        https_url(url)
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=5),
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            ) as client:
                deadline = time.monotonic() + 15
                with client.stream(
                    "POST" if data is not None else "GET",
                    url,
                    data=data,
                    auth=auth,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        raise ValueError("Provider request was unsuccessful.")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ValueError("Compressed provider responses are unsupported.")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                            raise ValueError("Provider response is too large.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Provider response must be an object.")
            return value
        except (httpx.HTTPError, ValueError) as error:
            raise DomainError(
                "auth.provider_unavailable", "Sign-in provider is unavailable. Try again later.", 503
            ) from error

    def discovery(self, provider: Provider) -> dict:
        value = self._json(provider.issuer.rstrip("/") + "/.well-known/openid-configuration")
        try:
            if value.get("issuer") != provider.issuer:
                raise ValueError("Discovery issuer mismatch.")
            for endpoint in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                https_url(value[endpoint])
            for field in (
                "response_types_supported",
                "id_token_signing_alg_values_supported",
                "code_challenge_methods_supported",
                "token_endpoint_auth_methods_supported",
            ):
                if field in value and (
                    not isinstance(value[field], list)
                    or not all(isinstance(item, str) for item in value[field])
                ):
                    raise ValueError("Invalid discovery metadata.")
            if "code" not in value.get("response_types_supported", []):
                raise ValueError("Authorization code flow is required.")
            if not SIGNING_ALGORITHMS.intersection(value.get("id_token_signing_alg_values_supported", [])):
                raise ValueError("A supported asymmetric signing algorithm is required.")
            if (
                "code_challenge_methods_supported" in value
                and "S256" not in value["code_challenge_methods_supported"]
            ):
                raise ValueError("PKCE S256 is required.")
        except (KeyError, TypeError, ValueError) as error:
            raise DomainError(
                "auth.provider_unavailable", "Sign-in provider configuration was not accepted.", 503
            ) from error
        return value

    def start(self, provider_id: str, client: str) -> tuple[str, str]:
        provider = self.provider(provider_id)
        # Commit attempt counters before external I/O, keeping the SQLite writer available.
        with self.database.transaction(write=True) as repo:
            self.identity.rate_limit(
                repo, self.identity.rate_key(provider_id, client, "oidc-start"), maximum=20, consume=True
            )
        metadata = self.discovery(provider)
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        at = now()
        redirect_uri = self.redirect_uri(provider.id)
        with self.database.transaction(write=True) as repo:
            repo.execute("DELETE FROM oidc_transactions WHERE expires_at <= :now", {"now": at})
            repo.insert(
                "oidc_transactions",
                {
                    "state_hash": digest(state),
                    "provider_id": provider.id,
                    "browser_hash": digest(browser),
                    "nonce": nonce,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "created_at": at,
                    "expires_at": after(TRANSACTION_SECONDS, at),
                },
            )
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": provider.client_id,
                "redirect_uri": redirect_uri,
                "scope": "openid",
                "max_age": "0",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return metadata["authorization_endpoint"] + "?" + query, browser

    def _consume(self, provider_id: str, state: str, browser: str) -> dict:
        require(
            bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", state))
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", browser)),
            "auth.oidc_failed",
            "Sign-in could not be completed.",
            401,
        )
        with self.database.transaction(write=True) as repo:
            transaction = repo.one("oidc_transactions", state_hash=digest(state))
            require(
                transaction is not None
                and transaction["provider_id"] == provider_id
                and transaction["expires_at"] > now()
                and hmac.compare_digest(transaction["browser_hash"], digest(browser)),
                "auth.oidc_failed",
                "Sign-in could not be completed.",
                401,
            )
            assert transaction is not None
            repo.delete("oidc_transactions", state_hash=digest(state))
        return transaction

    def _claims(self, provider: Provider, metadata: dict, token: Any, nonce: str, started_at: str) -> dict:
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 65536:
                raise ValueError("ID token is missing or too large.")
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            if (
                algorithm not in SIGNING_ALGORITHMS
                or algorithm not in metadata["id_token_signing_alg_values_supported"]
                or header.get("crit")
            ):
                raise ValueError("Unsupported token header.")
            keys = self._json(metadata["jwks_uri"]).get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 100:
                raise ValueError("Invalid signing keys.")
            candidates = [
                key
                for key in keys
                if isinstance(key, dict)
                and ("kid" not in header or key.get("kid") == header["kid"])
                and key.get("use", "sig") == "sig"
                and key.get("alg", algorithm) == algorithm
                and "verify" in key.get("key_ops", ["verify"])
            ]
            if len(candidates) != 1 or any(name in candidates[0] for name in ("d", "p", "q", "k")):
                raise ValueError("No unique public signing key.")
            signing_key = jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm).key
            if algorithm == "RS256" and getattr(signing_key, "key_size", 0) < 2048:
                raise ValueError("RSA signing keys require at least 2048 bits.")
            if (
                algorithm == "ES256"
                and getattr(getattr(signing_key, "curve", None), "name", None) != "secp256r1"
            ):
                raise ValueError("ES256 requires a P-256 signing key.")
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                audience=provider.client_id,
                issuer=provider.issuer,
                leeway=30,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce", "auth_time"]},
            )
            subject = claims["sub"]
            if (
                not isinstance(subject, str)
                or not 1 <= len(subject) <= 255
                or any(ord(c) < 32 or ord(c) > 126 for c in subject)
            ):
                raise ValueError("Invalid subject.")
            if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], nonce):
                raise ValueError("Nonce mismatch.")
            if any(
                isinstance(claims[name], bool)
                or not isinstance(claims[name], (int, float))
                or not math.isfinite(claims[name])
                for name in ("exp", "iat", "auth_time")
            ):
                raise ValueError("Invalid token timestamps.")
            if claims["iat"] < time.time() - 600 or claims["exp"] <= claims["iat"]:
                raise ValueError("ID token is stale.")
            if (
                not datetime.fromisoformat(started_at).timestamp() - 30
                <= claims["auth_time"]
                <= time.time() + 30
            ):
                raise ValueError("Fresh provider authentication is required.")
            audience = claims["aud"]
            if not isinstance(audience, (str, list)) or (
                isinstance(audience, list) and not all(isinstance(a, str) for a in audience)
            ):
                raise ValueError("Invalid audience.")
            if (isinstance(audience, list) and len(audience) > 1) or "azp" in claims:
                if claims.get("azp") != provider.client_id:
                    raise ValueError("Authorized party mismatch.")
            return claims
        except (jwt.PyJWTError, TypeError, ValueError, KeyError, OverflowError) as error:
            raise DomainError("auth.oidc_failed", "Sign-in could not be completed.", 401) from error

    def complete(
        self,
        provider_id: str,
        state: str,
        browser: str,
        code: str,
        request_id: str,
        *,
        response_issuer: str | None = None,
        rejected: bool = False,
        client: str = "local",
    ) -> str:
        # Failed callbacks produce audit events, so bound them before accepting attacker-controlled state.
        with self.database.transaction(write=True) as repo:
            self.identity.rate_limit(
                repo, self.identity.rate_key("all", client, "oidc-callback"), maximum=60, consume=True
            )
        try:
            provider = self.provider(provider_id)
            transaction = self._consume(provider_id, state, browser)
            require(
                not rejected
                and 1 <= len(code) <= 4096
                and (response_issuer is None or response_issuer == provider.issuer),
                "auth.oidc_failed",
                "Sign-in could not be completed.",
                401,
            )
            metadata = self.discovery(provider)
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": transaction["redirect_uri"],
                "code_verifier": transaction["code_verifier"],
                "client_id": provider.client_id,
            }
            auth = None
            secret = read_client_secret(provider)
            if secret is not None:
                methods = metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
                if "client_secret_basic" in methods:
                    auth = httpx.BasicAuth(quote(provider.client_id, safe=""), quote(secret, safe=""))
                elif "client_secret_post" in methods:
                    data["client_secret"] = secret
                else:
                    raise DomainError(
                        "auth.provider_unavailable", "Provider client authentication is unsupported.", 503
                    )
            response = self._json(metadata["token_endpoint"], data=data, auth=auth)
            claims = self._claims(
                provider, metadata, response.get("id_token"), transaction["nonce"], transaction["created_at"]
            )
            with self.database.transaction(write=True) as repo:
                binding = repo.one(
                    "external_identities",
                    provider_id=provider.id,
                    issuer=provider.issuer,
                    subject=claims["sub"],
                )
                user = repo.one("users", id=binding["user_id"]) if binding else None
                require(
                    user is not None
                    and user["status"] == "active"
                    and not user["is_system_admin"]
                    and user["id"] != ANONYMOUS_USER_ID,
                    "auth.oidc_failed",
                    "Sign-in could not be completed.",
                    401,
                )
                assert user is not None
                repo.audit(user["id"], "auth.login", "user", user["id"], request_id, {"method": "oidc"})
                _view, token = self.identity.start_session(repo, user, request_id, method="oidc")
                return token
        except (DomainError, OSError, ValueError) as error:
            with self.database.transaction(write=True) as repo:
                repo.audit(None, "auth.login_failed", "session", "redacted", request_id, {"method": "oidc"})
            raise DomainError("auth.oidc_failed", "Sign-in could not be completed.", 401) from error

    def list_identities(self, repo, actor: Actor, user_id: str | None = None) -> list[dict]:
        actor.authorize("owner")
        rows = repo.find("external_identities", **({"user_id": user_id} if user_id else {}))
        return [{key: row[key] for key in IDENTITY_FIELDS} for row in rows]

    def link(self, repo, actor: Actor, body: dict) -> dict:
        actor.authorize("owner", recent=True)
        provider = self.provider(body["provider_id"])
        subject = body["subject"]
        require(
            isinstance(subject, str)
            and bool(subject.strip())
            and len(subject) <= 255
            and all(32 <= ord(c) <= 126 for c in subject),
            "auth.subject_invalid",
            "Use the provider's exact subject identifier, up to 255 ASCII characters.",
            422,
        )
        user = repo.one("users", id=body["user_id"])
        require(user is not None, "user.not_found", "User not found.", 404)
        require(
            not user["is_system_admin"] and user["id"] != ANONYMOUS_USER_ID,
            "auth.system_identity",
            "The core system administrator must use local sign-in.",
            403,
        )
        require(
            user["status"] == "active", "user.disabled", "Enable this account before linking a sign-in.", 409
        )
        require(
            repo.one("external_identities", issuer=provider.issuer, subject=subject) is None,
            "auth.identity_exists",
            "This provider identity is already linked.",
            409,
        )
        row = {
            "id": new_id(),
            "user_id": user["id"],
            "provider_id": provider.id,
            "issuer": provider.issuer,
            "subject": subject,
            "created_at": now(),
        }
        repo.insert("external_identities", row)
        repo.audit(actor.user["id"], "auth.identity_linked", "user", user["id"], actor.request_id)
        return row

    def unlink(self, repo, actor: Actor, identity_id: str) -> None:
        actor.authorize("owner", recent=True)
        row = repo.one("external_identities", id=identity_id)
        require(row is not None, "auth.identity_not_found", "Linked identity not found.", 404)
        repo.delete("external_identities", id=identity_id)
        for session in repo.find("sessions", user_id=row["user_id"]):
            repo.update("sessions", {"revoked_at": now()}, token_hash=session["token_hash"])
        repo.audit(actor.user["id"], "auth.identity_unlinked", "user", row["user_id"], actor.request_id)
