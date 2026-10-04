# Manage users and sign-ins

Sign in with an owner account, then open **System → Users** or **System → Authentication**. Administrative pages and their APIs enforce owner permissions. Sign in again before a sensitive change if the session is more than fifteen minutes old; return to the page and retry after authentication.

## Accounts and permissions

| Role | Permissions |
| --- | --- |
| Viewer | Read boxes, contents and photos; search and scan. |
| Editor | Viewer access plus create/edit inventory, photos and labels; review AI suggestions. |
| Owner | Editor access plus users, sign-ins, system maintenance, backups and permanent purge. |

Add a user with a local username, display name, role and unique password. Existing usernames identify the account and are not renamed. Edit the display name, role or status in the user form. Resetting a password, changing a role or changing account status revokes that user's sessions. A stale edit is rejected; reload before applying it again.

Disable an account to stop its access without deleting its inventory or audit history. Re-enable only after reviewing its role and provider identities. The core system administrator is marked in the list and cannot be disabled or demoted. Keep that administrator's password in a password manager available to the responsible operator.

## Sessions and sign-in history

Open **Authentication** to inspect recent sessions and authentication events. Filter by user to investigate a specific account. Each session shows its method, creation time, last activity, expiry and whether it is active or current. Session activity updates at most once per minute. The table intentionally excludes raw cookies, token hashes and secrets.

Revoke one session to sign that browser out on its next authenticated request, or revoke all sessions for the selected user. Revoking your current session also signs you out. When anonymous access is enabled, a revoked browser may regain the configured anonymous inventory permissions; revocation does not change that host setting.

The event list includes successful/failed sign-ins, sign-out and administrative authentication changes. Failed usernames are not retained as public audit identifiers. Lists are bounded to recent records; they are an operational view, not an unlimited audit export or external monitoring service.

## Linked provider identities

The same panel lists configured providers and exact subject bindings. Configuration and client secrets are managed on the host, while owners manage who is allowed to sign in. Add a binding only after verifying the identity with the provider administrator. Unlinking revokes the user's sessions. See [Authentication setup](/help/authentication) for registration and configuration.

## Change your own password

Open **Account**, enter the current password and a new passphrase. A successful change replaces the current session and revokes other sessions. An owner can reset another user's password in Users. Passwords and provider tokens are never displayed by the administrative panel.

## Recover the core administrator

If no working owner session remains, use the local host console. Load the same environment/configuration and data directory as the installation. Stop web and worker before running:

```sh
.venv/bin/boxen admin-password
```

The command prompts privately for the replacement password and confirmation, resets only the core administrator, records the change and revokes its sessions. Do not pass the password in command-line arguments or paste it into chat. Restart services and sign in with the core account's username. This requires host access; it is not a remote password-reset link.

For Docker, stop web and worker, then run the same command interactively in the existing app volume:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml stop web worker
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps web admin-password
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never web worker
```

Retain any selected overlays. Restore a missing pepper from the installation's protected secret copy before attempting password recovery. Replacing a pepper invalidates existing peppered passwords. See [Recovery](/help/recovery) for full installation recovery.

## System maintenance

System shows database, storage, worker and AI state. A missing optional model does not prevent manual inventory work. Backups require a running worker when queued in the UI. Use Maintenance to verify data and search or rebuild derived search. An original photo cannot be recovered by rebuilding its thumbnail; restore it from a verified backup.

Before an upgrade, stop services, preserve a verified backup and the complete secret/configuration/TLS state, then perform the explicit migration. Afterward verify login, component status, a representative box and backup completion. Do not force a schema mismatch or discard SQLite journal files.
