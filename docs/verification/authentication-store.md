# Authentication store and administration verification

Date: 2026-10-03. Implementation verified with disposable databases and browsers,
then deployed to the existing native installation at the user's request to test
authentication. No live OAuth provider has been registered.

## Native deployment and testing

The native installation at `https://192.0.2.10:8443` now runs schema 0003 and
frontend `index-CZIeHnF3.js`, including authentication, administration, help and
collection names on labels. Web and worker were restarted with their original
configuration; Caddy, its existing CA, and local AI remained running unchanged.

This installation has no named account yet. Open `/setup`, copy the existing
one-time token privately from `.local/boxen/data/secrets/setup-token`, keep the
suggested username `admin` or choose another, enter a display name, and choose a
unique password of at least twelve characters. Creating the first account makes
it the protected core administrator. No temporary password was assigned and the
setup token was not consumed during verification. Then sign out and back in at
`/login`, and test `/system/users` and `/system/authentication`. Anonymous
inventory editing remains enabled; administrative pages require an owner login.
OAuth testing requires configuring a real provider as described in Help.

Before the upgrade, an isolated database copy passed the actual migration and
application startup checks. The stopped installation's database, media, backups,
secrets, configuration, old static assets, service definitions and TLS state were
preserved under the private `.local/auth-deployment/2026-10-03` directory. Model
weights were left in their original location. The newly generated independent
pepper also has a protected recovery copy there. Do not publish this directory.

Live verification passed certificate-validated HTTPS readiness, desktop/mobile
setup rendering, public authentication/administration help, expected 401 without
a session and 403 for anonymous access on all five administrative API groups,
and Secure/HttpOnly/SameSite=Strict session-cookie flags. There were no browser
page errors. A live collection-label PDF contained its code and collection names.
All thirteen selected inventory/account/audit tables retained their pre-upgrade
row hashes; configuration, session secret and setup token were preserved. SQLite
integrity, foreign keys and search checks passed. Web and worker remained active
with zero restarts after launch. Private scripts and results are in
`.local/auth-deployment`; the first-owner form was deliberately left for the user
to choose their own credentials.

## Delivered behavior

- Schema 0003 preserves historical migrations and designates the oldest active
  local owner as the protected core administrator. New setup suggests `admin`,
  with a unique chosen password; no factory credential is shipped. API and SQLite
  guards prevent disabling, demoting, deleting or linking OAuth to that identity.
- Local password hashes use Argon2id with random salts and HMAC-SHA256 prehashing
  using a separate private 32-byte pepper. Legacy passwords upgrade on successful
  login. Initialization refuses to regenerate a missing established pepper;
  startup and restore reject a mismatching fingerprint.
- Owners can create/update/disable users, reset passwords, list/revoke sessions,
  inspect authentication events, and bind/unbind exact issuer/subject identities.
  Sensitive changes require recent authentication, CSRF and same-origin checks.
  Idempotent retries still enforce the caller's current owner role.
- Optional host-configured OIDC providers use authorization code, PKCE S256,
  browser-bound expiring state, nonce, asymmetric signature/issuer/audience/azp
  checks, and fresh `auth_time`. Provider access/refresh tokens are not stored.
  Callback errors are generic; start/callback attempts and responses are bounded.
  No email auto-linking, self-registration or provider role promotion is enabled.
- `boxen admin-password` provides interactive offline core-account recovery,
  requires the exclusive runtime lock, audits the reset and revokes sessions.
- `/help` exposes ten public topics covering setup, all configuration/storage,
  authentication, users/sign-ins, inventory, HTTPS/phones, backup/restore, local AI
  and remote AI. They ship in the local frontend and work without a help service.
- The optional `deploy/compose.oauth.yaml` mounts host provider configuration
  read-only and gives only web an additional outbound network. The default stack
  retains its existing local behavior.

## Verification

- Full backend suite: **771 passed**, two opt-in real-model tests skipped; **72/72**
  API operations exercised successfully. JUnit: `artifacts/auth-backend-final.xml`.
- Frontend: **184 unit tests passed**, TypeScript and production build passed.
- Browser: **14 distinct scenarios passed** (five administration, one first-owner
  setup/login, eight baseline inventory/access scenarios). The five administration
  scenarios also passed against the final staged build. Desktop/mobile screenshots
  inspected; axe reported no violations and no horizontal overflow.
- Ruff lint/format, mypy, Prettier, OpenAPI validation, contract/migration mirror
  comparisons and `git diff --check` passed.
- OAuth Compose overlay resolved with read-only config and web-only outbound
  networking. Docker app image `boxen:auth-check` built successfully (local image
  `d607f99f10e3`); network-disabled, non-root, read-only image smoke verified
  initialization, core-admin setup, pepper permissions, OAuth import and bundled
  help. The 53 focused packaging tests passed after the Docker help-copy change.
- Authentication browser verification used `.local/auth-build`, entry
  `index-DFeN3KtZ.js`; subsequent label-help edits produced the deployed
  `index-CZIeHnF3.js`. Disposable browser fixture ports were closed after testing.
  No release image was published.

The security cases cover legacy hashes, different salts, pepper loss/replacement,
unsafe file permissions, core-admin API/SQL protections, viewer denial, recent
owner checks, cross-browser and all-user session revocation, idempotency after
owner demotion, private-field redaction, offline lock fencing, known 0001/0002
backups, pepper preservation at a custom path, and restore quarantine.

The provider suite uses real signed RSA/EC JWTs and HTTP mock transports with
separate browser cookies. It covers valid code exchange, PKCE, wrong issuer or
audience, invalid/missing/expired claims, nonce/state/browser binding, replay,
missing/stale authentication time, duplicate callback parameters, provider
mix-up, disabled users/providers, unbound subjects, no email/role escalation,
link ownership/uniqueness/core constraints, unlink revocation, malformed keys,
unsupported algorithms, response bounds, HTTPS and secret-file permissions.

Browser checks exercise the real disposable Boxen backend. OAuth provider
navigation is intercepted for the UI test; actual third-party provider/browser
consent and network interoperability have not been qualified. Backend tests
exercise the code exchange and signature validation separately.

## Installation handoff

1. Review [setup](../help/getting-started.md) and
   [authentication configuration](../help/authentication.md).
2. Preserve a verified pre-upgrade backup, complete installation/secret copy,
   existing configuration and TLS state. Use the running owner Backups page or the previous release CLI to create the pre-upgrade backup. Stop web and worker. Install the updated
   dependencies and built frontend, then run `boxen init` with the existing data
   directory/configuration. This is an explicit offline migration to 0003.
3. Restart services and check login/System. Existing owners retain their username
   and password; the oldest active local owner becomes core. For an installation
   without an owner, finish the one-time host-token setup and choose a unique
   administrator password. Never expose that token or password in chat/logs.
4. Register the chosen OIDC client, exact HTTPS redirect URI and private secret,
   configure the provider file, restart web, then explicitly bind authorized
   subjects in the owner panel. Confirm a real sign-in with that provider before
   relying on it operationally. Keep the core local login available.

The native cutover above is complete. No Docker image publication, host network
changes, provider credentials or live named-account provisioning were performed.
