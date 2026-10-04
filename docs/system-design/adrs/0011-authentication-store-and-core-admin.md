# ADR-0011: Authentication store and protected core administrator

Status: accepted for source implementation, 2026-10-03. Live migration is a separate
operator step. This supersedes local-only identity and unpeppered-password claims
in the original baseline; ADR-0005's configurable anonymous permissions remain.

## Decision

Keep Boxen as the account/role authority and session issuer. Add optional OIDC
relying-party login with authorization code and PKCE S256. This does not make
Boxen an OAuth authorization server or issue third-party bearer credentials.

The first setup owner, or oldest active local owner on upgrade, is the immutable
core system administrator. It must remain an active owner with local password
sign-in; neither API nor persistence may remove, disable, demote or link an
external identity to it. Setup suggests `admin` but requires a unique chosen
password; no shared/default password is shipped. Host recovery is interactive,
offline, audited and revokes the core administrator's sessions.

Every new/reset local password uses a random salt and Argon2id over a
HMAC-SHA256 prehash with a separate random installation pepper. Legacy Argon2
hashes upgrade after successful login. A version marker disambiguates schemes.
Private key files are never returned by the API; normal inventory backups omit
them. Missing established or mismatching peppers fail closed. Operators must
retain protected installation-secret recovery copies independently of snapshots.

OIDC providers are explicitly configured by the host operator. Owners bind exact
issuer/subject identifiers to existing local users. There is no email linking,
JIT registration or role mapping. OAuth failure cannot remove the core local
recovery path. Code exchange validates signed ID tokens with approved asymmetric
algorithms, issuer/audience/azp/nonce/time and fresh auth_time. State is browser
bound, expiring and single-use; tokens remain transient. Network calls use
verified HTTPS, bounded responses/timeouts and no automatic redirects or proxy
inheritance. Provider outages affect only provider login.

Owner administration lists users, bounded recent sessions/events, configured
providers and linked identities. Mutations require current role, recent sign-in,
origin and CSRF checks. Role/status/password changes and identity unlink revoke
sessions. Normal session cookies remain opaque, HttpOnly, same-origin and Secure
on HTTPS. The separate OIDC transaction cookie uses SameSite=Lax only for callback
correlation. Existing independent sessions remain valid when a provider is disabled;
operators must deliberately revoke those sessions when withdrawing access.

## Migration and operations

Migration 0003 adds the core marker and persistence guards, public session IDs,
authentication methods, external identities and transient OIDC state. Historical
0001/0002 SQL payloads are immutable. Upgrade is explicit and offline. Restore
accepts pinned historical schemas, upgrades a staging copy, checks the pepper,
revokes sessions and discards outstanding provider transactions.

Ten public local help pages cover configuration and management, including native
and Docker deployment. An optional Compose OAuth overlay gives only web outbound
provider connectivity and mounts private configuration read-only. Core inventory
and local authentication retain offline operation. Real provider registration and
client credentials are supplied by the operator, not synthesized by the app.

See [authentication setup](../../help/authentication.md),
[administration](../../help/administration.md), [OpenAPI](../contracts/openapi.yaml),
[migration](../contracts/migrations/0003_authentication.sql) and
[verification](../../verification/authentication-store.md).
