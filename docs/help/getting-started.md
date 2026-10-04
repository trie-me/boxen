# Start here

Boxen stores box descriptions, photos, contents, tags, collections, accounts and sign-in records on the computer running it. The web service serves the app; the worker performs backups, maintenance and optional image analysis. SQLite must live on a local filesystem. Every process must use the same data directory and configuration.

## Set up a new installation

1. Follow the [container quick start](/help/deployment), or [native development](/help/development) if you are working on the code. The Docker build supplies Python, Node and package managers; you do not need them on the host.
2. For Docker, copy `deploy/.env.example` to `deploy/.env` and choose the host, bind address, HTTPS port and anonymous-access mode. Compose derives the browser origin and uses persistent named volumes. For native operation, configure `BOXEN_ORIGIN` and a persistent `BOXEN_DATA_DIR` directly.
3. Build the images, run the `init` service, then start web, worker and Caddy using the quick-start commands. Keep the one-time setup token private. Export and trust this installation's public CA certificate on your devices.
4. Open [Set up administrator](/setup) and enter the setup token. The suggested username is `admin`; choose your own display name and a unique password of at least 12 characters. There is no shared factory password. This account becomes the protected core system administrator and always signs in locally.
5. Sign in, open System, check component status, and create a verified backup. Optional AI and OIDC can be configured afterward.

Initialization also generates private session and password-pepper keys. Keep them with the installation. Re-running initialization preserves accounts and credentials; it does not reset a password.

## Choose who can use Boxen

The default `BOXEN_ANONYMOUS_ACCESS=editor` permits anyone reaching the installation to edit inventory. Set it to `viewer` for anonymous read-only access, or `off` to require an account. After changing it in Docker's `.env`, run the quick start's `up -d` command to recreate affected services; `restart` alone does not apply the new value. For native operation, restart web and worker with matching configuration. Anonymous access never grants administration. Create the core administrator even if you deliberately keep anonymous inventory access enabled.

Use [Users](/system/users) to add accounts with viewer, editor or owner roles. Use [Authentication](/system/authentication) to inspect sign-ins and sessions and to link identities from a configured OpenID Connect provider. See [Authentication setup](/help/authentication) and [Administration](/help/administration).

## Upgrade an existing installation

Preserve the current data directory, inventory, keys, configuration and TLS state. Take and verify a backup before switching releases. Stop web and worker; run the new release's `boxen init` against the existing configuration; then restart and check System. This release introduces schema **0003** for authentication. Startup refuses an unmigrated database; it never silently migrates live data.

Migration designates the oldest active local owner as the core system administrator. Existing passwords continue to work and gain peppered storage on their next successful login. Check that account and keep its credentials available before enabling OAuth. See [Recovery](/help/recovery) before any restore or rollback.

## Phones, HTTPS and offline operation

Use the server's LAN address from your phone; `127.0.0.1` means the phone itself. The browser address, reverse proxy and `BOXEN_ORIGIN` must agree. Use [Native HTTPS](/help/native-https) or the Docker deployment guide for certificates. Live camera access requires a secure browser context and camera permission. Uploading a QR image or typing a code is available if camera access is unavailable.

Local password sign-in and inventory remain available without internet access. OAuth needs the configured identity provider; remote AI needs its configured endpoint. Neither is required for the core administrator. Keep Boxen on your intended private network; the default configuration is not a public hosting setup.
