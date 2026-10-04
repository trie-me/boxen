# Native Tailscale HTTPS

Addresses and filesystem paths below are anonymized examples. Use your own
installation's private settings when following these historical instructions.

**Historical native setup:** superseded by the
[container deployment](container-tailnet.md) on 2026-10-04. Native services are
stopped and their data is retained for rollback. Use the container runbook for
current restart commands; do not restart the stale native copy alongside it.

The native setup introduced **https://boxen.example-tailnet.ts.net:8443**.
Connect the client to Tailscale and include port `8443` in the address.
This uses the existing native installation and Caddy local certificate authority.
Clients that already trust the Boxen CA retain that trust; other clients need the
[existing certificate setup](native-https.md#one-time-motorola-android-setup).
The public certificate is also available at
`http://boxen.example-tailnet.ts.net:8000/trust/boxen-local-ca.crt`.

Tailscale Serve is disabled for this tailnet, so the proxy binds directly to this
host's Tailscale IPv4 and IPv6 addresses. No Serve or Funnel configuration was
installed. The application remains on loopback `127.0.0.1:8000`.

## Configuration and restart

- App configuration: `.local/boxen/app.toml`, with origin
  `https://boxen.example-tailnet.ts.net:8443` (no trailing slash).
- Proxy configuration: `deploy/native-tailnet.Caddyfile`.
- Tailscale bind addresses: `100.64.0.10` and
  `fd7a:115c:a1e0::1234`.
- Existing CA state: `.local/boxen-https/state`; public certificate only in
  `.local/boxen-https/public`. Host trust installation remains disabled.
- Existing data, authentication configuration, frontend and local AI are retained.

For a routine restart of the current running units:

```sh
systemctl --user restart boxen-web.service boxen-worker.service boxen-proxy.service
```

These are the existing transient user services, not newly installed boot units.
To recreate the proxy after stopping its current unit, use:

```sh
cd /path/to/boxen
systemd-run --user --unit=boxen-proxy --collect \
  --working-directory=/path/to/boxen \
  --property=Restart=on-failure --property=RestartSec=3 \
  --property=TimeoutStopSec=30 --property=UMask=0077 \
  --property=NoNewPrivileges=yes \
  --setenv=LOCAL_TLS_STATE=/path/to/boxen/.local/boxen-https/state \
  --setenv=LOCAL_TLS_PUBLIC=/path/to/boxen/.local/boxen-https/public \
  --setenv=LOCAL_TLS_HOST=192.0.2.10 \
  --setenv=TAILNET_HOST=boxen.example-tailnet.ts.net \
  '--setenv=TAILNET_BIND=100.64.0.10 [fd7a:115c:a1e0::1234]' \
  /path/to/boxen/.local/boxen-https/bin/caddy run \
  --config /path/to/boxen/deploy/native-tailnet.Caddyfile --adapter caddyfile
```

The old LAN HTTPS and HTTP addresses accept reads only, redirecting to the new
origin while preserving the path and query. Their public `/trust/` pages remain
available. Writes to the old addresses return `400` so clients reload at the new
origin. Tailscale HTTP port `8000` behaves the same way. No proxy wildcard
listeners are used.

Browser storage is scoped to the new origin: sign in again and re-pin labels
there if needed. Existing inventory and collections remain in the same database.

## Verified cutover

Web, worker and proxy restarted successfully; the AI service stayed running.
Verification on the host passed with certificate validation enabled:

- Readiness, legacy redirects and rejection of writes to old addresses.
- Secure session cookies, anonymous admin restrictions and CSRF/origin checks.
- Two pinned labels, persistence after reload, combined PDF download and collection
  printing navigation at desktop and mobile widths; no page errors or inventory
  mutations.
- Unchanged deployed frontend (`index-CZIeHnF3.js`) and 12 existing
  business/account/audit/schema/identity table hashes; SQLite integrity and
  foreign-key checks pass.
- Caddy configuration validation and exact interface bindings.

This preserves the authentication/schema 0003 and collection-label release
deployed on 2026-10-03. Remote-device connectivity and physical printer alignment
were not exercised during this restart.

## Rollback

Private pre-cutover snapshots are in `.local/tailnet-binding/2026-10-04/`:
`previous-app.toml`, `previous-proxy.Caddyfile`, an online `before.sqlite3`
snapshot, table hashes and the deployed index checksum. No schema or inventory
change was made; an address rollback does not require restoring the database.

Restore `previous-app.toml` to `.local/boxen/app.toml` with mode `0600`, then restart
web and worker. Stop the proxy and recreate it using the command above with
`deploy/native.Caddyfile`, omitting both `TAILNET_*` environment arguments. This
restores the previous `https://192.0.2.10:8443` origin and LAN proxy. Preserve
the CA state throughout.
