# Authentication setup

Boxen supports local username/password sign-in and OpenID Connect (OIDC), the identity layer on OAuth 2.0. Local roles remain authoritative. Provider emails, groups and claimed roles do not grant access automatically.

## Core system administrator

First-owner setup creates the protected local administrator. The setup form suggests `admin`; there is no factory password. That account cannot be disabled, demoted or linked to an OAuth identity. It remains usable during an identity-provider outage. On upgrade, the oldest active local owner becomes the core administrator. Other owners can manage users, reset passwords, inspect sessions and manage explicit provider bindings.

A password must contain at least 12 characters and at most 1024 UTF-8 bytes. Passwords are not trimmed. Boxen rejects a small list of common passwords and rate-limits failed sign-in attempts. Password managers and paste are supported.

Passwords use Argon2id (64 MiB, three iterations, four lanes) with a fresh random 16-byte salt. Before hashing, Boxen applies HMAC-SHA256 with a separate installation pepper; the versioned stored value identifies this scheme. The pepper defaults to `secrets/password.pepper` under `BOXEN_DATA_DIR`, or `BOXEN_PASSWORD_PEPPER_FILE` can select a protected file. It is not stored with password hashes in SQLite or included in normal inventory backups. Legacy Argon2 passwords upgrade after successful verification. Missing or unsafe pepper files fail closed; do not delete or replace a pepper to troubleshoot sign-in.

## Configure an OIDC provider

1. Register a confidential web client with your chosen OIDC provider. Allow the authorization-code flow and PKCE S256. Boxen validates RS256 (RSA at least 2048 bits) and ES256 (P-256) ID tokens. The provider must honor `max_age=0` and return a fresh `auth_time` claim. Do not enable the implicit or password grant for Boxen.
2. Set the client's exact redirect URI to `BOXEN_ORIGIN` plus `/api/v1/auth/oidc/PROVIDER_ID/callback`. For example, a provider ID of `work` at `https://boxen.example:8443` uses `https://boxen.example:8443/api/v1/auth/oidc/work/callback`. The example hostname is a placeholder. Your provider must permit your actual HTTPS address.
3. Save a provider JSON file and a separate private client-secret file on the host. Relative secret-file paths resolve against the JSON file's directory. Restrict the secret to its service owner with mode `0600`; protect the parent directory and configuration against untrusted writes. Do not put the client secret in source control, a URL or browser code.
4. Set `BOXEN_OAUTH_PROVIDERS_FILE` to the JSON file's absolute path and restart the web service. Host configuration is read at startup. Inspect **System → Authentication → Sign-in providers** for the configured callback address.

Example JSON (replace every example value):

```json
{
  "providers": [
    {
      "id": "work",
      "label": "Work account",
      "issuer": "https://identity.example/realms/boxen",
      "client_id": "boxen",
      "client_secret_file": "work-client.secret",
      "enabled": true
    }
  ]
}
```

Issuer and discovered endpoints must use HTTPS with valid certificates. Discovery is at the issuer's `/.well-known/openid-configuration` URL. Boxen does not follow redirects or inherit proxy settings for these requests. Set a provider's `enabled` to `false` and restart to stop new sign-ins; revoke its users' existing Boxen sessions separately. Removing an entry does not delete accounts or inventory. Keep issuer/client identifiers stable: changing the provider configuration is an identity migration, not a label edit.

For native operation, use the same environment/configuration source that launches web:

```sh
export BOXEN_OAUTH_PROVIDERS_FILE=/absolute/private/path/providers.json
```

For Docker, add `deploy/compose.oauth.yaml` and set `BOXEN_OAUTH_CONFIG_DIR` in `deploy/.env` to the absolute directory containing `providers.json` and its referenced secret files. Ensure UID 10001 can read the directory and mode-0600 files. The overlay mounts it read-only at `/run/boxen-oauth` and adds outbound network access to web for the selected provider. Retain the overlay on subsequent web lifecycle commands:

```sh
docker compose --env-file deploy/.env -p boxen \
  -f deploy/compose.yaml -f deploy/compose.oauth.yaml \
  up -d --no-build --pull never web worker caddy
```

Keep any other overlays your installation already uses. OAuth configuration is optional; the base installation remains local.

## Grant a user provider sign-in

1. Create the Boxen user under **System → Users**, choosing the least necessary role and a unique local password.
2. Obtain that person's exact, stable OIDC `sub` claim for this issuer and client from your identity-provider administrator. A subject can differ by client. Do not substitute their email address unless it is literally the issued subject.
3. Sign in as an owner within the last 15 minutes. Open **System → Authentication**, select the Boxen user and configured provider, and add the exact subject binding.
4. Have the user select that provider on the Boxen login page. Boxen grants only the stored user's current role and rejects disabled accounts or unlinked subjects.

One issuer/subject belongs to one Boxen user. There is no self-registration, automatic email linking or provider-role synchronization. The core system administrator is local-only. Removing a binding revokes that user's Boxen sessions. Disabling the local user blocks both local and provider sign-in.

## Session security and failures

OAuth uses a one-time five-minute state bound to the initiating browser, PKCE S256, a nonce and signed ID-token validation for issuer, audience and time. Every provider sign-in requests fresh authentication (`max_age=0`) and verifies `auth_time`; an old provider session alone does not satisfy recent-owner authentication. Provider access and refresh tokens are not kept as application credentials. Boxen issues its own opaque, HttpOnly session cookie, with Secure on HTTPS and same-origin CSRF checks for mutations.

Local sessions expire after seven days or twelve hours of inactivity. Sensitive administrative changes require sign-in within the last fifteen minutes. Signing out revokes the current Boxen session. A role, status or password change revokes the user's existing sessions. Boxen sign-out does not sign out of the provider globally.

If provider sign-in fails, start again from Boxen's login page. Check the exact callback URI, host clock, TLS certificates, provider availability and exact subject binding. A reused, expired or different-browser callback is deliberately rejected. The public error does not expose provider tokens or account existence. The protected local administrator remains the recovery path. See [Administration](/help/administration) for session revocation and password recovery.

Design references: [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html), [OAuth security best practice (RFC 9700)](https://www.rfc-editor.org/rfc/rfc9700.html), and [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
