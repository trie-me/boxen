# Deployment and local HTTPS

Run commands from the repository root. These instructions describe the current source, not every intended capability in the design baseline. The existing native installation now uses [local HTTPS with Motorola setup](native-https.md); the Compose instructions below describe a separate deployment option, not a migration of that inventory.

## Preflight and configuration

Use a local filesystem with working SQLite/WAL locking, enough space for originals, derivatives, backups and a complete restore copy, and a protected host account. Production refuses configured reserve limits below 2 GiB and 5%; uploads/backups may fail before the disk is full. A comprehensive installer/preflight command is not implemented.

`BOXEN_CONFIG_FILE=/absolute/path/config.toml` loads flat TOML settings; recognized `BOXEN_*` environment variables override them. [local.example.toml](../../deploy/local.example.toml) is a native-development example. Keep settings identical for web, worker and CLI. Do not pass Compose-only variables such as `BOXEN_HOST` into a native Boxen process: unknown `BOXEN_*` fields are rejected.

| Setting | Current behavior |
| --- | --- |
| `BOXEN_ENV` | `production` requires HTTPS; `development` permits explicit trusted-LAN HTTP as well as loopback. LAN HTTP is unencrypted and live browser camera needs HTTPS. |
| `BOXEN_ORIGIN` | Exact browser origin, including nonstandard port, with no trailing slash/path. Compose defaults to `https://localhost:8443`. Host and mutation Origin are checked. |
| `BOXEN_DATA_DIR` | Native: explicitly choose an absolute local path. Compose: `/var/lib/boxen/data`, inside the `boxen-data` volume mounted at `/var/lib/boxen`. |
| `BOXEN_ANONYMOUS_ACCESS` | `editor` default allows ordinary editing without an account; `viewer` is read-only; `off` requires login. Neither anonymous mode permits administration. |
| `BOXEN_AI_PROFILE` | Unset means no model. The base Compose file includes no inference service. |
| `BOXEN_AI_BASE_URL` | Default private `http://boxen-ai:8080`; use `http://127.0.0.1:8080` for a native local runtime. |
| `BOXEN_WORKER_SLOTS` | Only `1` is supported. Run one worker. |
| `BOXEN_BACKUP_RETENTION` | Defaults to `14`, but automatic pruning is not implemented. |

Compose-only interpolation variables are `BOXEN_HOST` (default `localhost`), `BOXEN_HTTPS_PORT` (`8443`) and `BOXEN_BIND_ADDRESS` (`127.0.0.1`). Change host/port only together with the exact application origin. The current configuration exposes no HTTP port, web port, Caddy admin port or AI port. Web and worker use an internal network; only Caddy also joins an ingress bridge so Docker can publish its loopback HTTPS port. Caddy listens on unprivileged container port 8443 with all capabilities dropped and its binary's file capabilities removed. Caddy uses its own internal CA without public ACME and does not install trust on your host automatically. The proxy ingress bridge technically permits outbound connections, but no external service is required or configured. mDNS/DNS advertising is not implemented.

The shared web/worker volume is writable because upload finalization currently happens in web. Both run as UID/GID 10001, with read-only root filesystems, dropped capabilities, bounded temporary storage and no privilege escalation. Each application process has a 330-second stop grace period for the maximum 300-second inference timeout. Logs rotate at three 10 MiB files per service; the design's time-based retention is not implemented.

**Existing installations:** the current layout places data under `/var/lib/boxen/data` so restore can rename it to a sibling quarantine on the same filesystem. Earlier manifests used `/var/lib/boxen` itself. Do not initialize a new empty installation over that older volume layout; stop services, preserve the volume, and migrate the existing complete tree into a child directory before adopting this manifest. That migration has not been rehearsed here.

## First owner and CA trust

Use the build/init/up sequence in the [README](../../README.md). `init` creates the schema, installation identity and protected session/setup secrets. Startup does not automatically initialize a missing database. Keep the printed token out of shared logs and messages. If initial output was lost before setup, read the existing token only at your host console:

```sh
docker compose -p boxen -f deploy/compose.yaml run --rm --no-deps --entrypoint python web -c 'from pathlib import Path; print(Path("/var/lib/boxen/data/secrets/setup-token").read_text())'
```

After Caddy starts, export its **public root certificate**, display its fingerprint, and test without disabling TLS verification:

```sh
mkdir -p .local/boxen-trust
docker compose -p boxen -f deploy/compose.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt .local/boxen-trust/root.crt
openssl x509 -in .local/boxen-trust/root.crt -noout -subject -fingerprint -sha256
curl --fail --cacert .local/boxen-trust/root.crt https://localhost:8443/api/v1/health/ready
```

Compare the SHA-256 fingerprint through a trusted host-console channel before importing the root into an OS/browser trust store. Only distribute `root.crt`; the Caddy volume also contains private CA keys and must remain protected. Browser trust installation differs by OS/browser; phone trust and secure-context camera behavior still require real-device testing. The application currently has no authenticated CA-download/fingerprint page.

Open `https://localhost:8443/setup` on the host and create the owner with the one-time token. There is no preconfigured password. Anonymous browsing does not grant administration. To require accounts, start/recreate services with `BOXEN_ANONYMOUS_ACCESS=off` set in your Compose environment.

`localhost` on a phone refers to the phone, not this server. For immediate native trusted-LAN HTTP, use the [README LAN startup](../../README.md#phones-and-other-devices-on-your-lan); it does not require Docker or a certificate for ordinary inventory/upload operations.

## LAN HTTPS

Use this for encrypted traffic and live browser-camera scanning. For an **existing Compose installation**, stop/recreate its services with a matching LAN address and exact origin; example for a host that owns `192.0.2.10`:

```sh
export BOXEN_BIND_ADDRESS=192.0.2.10
export BOXEN_HOST=192.0.2.10
export BOXEN_ORIGIN=https://192.0.2.10:8443
export BOXEN_ANONYMOUS_ACCESS=editor
docker compose -p boxen -f deploy/compose.yaml config --quiet
docker compose -p boxen -f deploy/compose.yaml up -d --no-build --pull never web worker caddy
```

For a new Compose installation, use these same variables for the README build/init/up sequence. Do **not** switch an existing native installation to the default empty Compose volume: that would show a different inventory, not migrate your data. Native installations can instead keep their same data directory and loopback backend behind a locally installed reverse proxy, with its exact public HTTPS origin configured in Boxen.

Open `https://192.0.2.10:8443` on both host and phones. Permit only the HTTPS port through the host firewall from the trusted LAN. Do not forward it at the router. Caddy issues a local certificate; export its public root certificate as above and deliberately install/trust it on each device after checking the fingerprint. Use the LAN HTTPS URL in the certificate-verifying curl check, not `localhost`. A successful desktop request alone is not proof of phone reachability or phone trust. Verify a phone can create a box, upload a photo, and start/stop the live QR camera after granting permission. No public DNS, public ACME, cloud tunnel or external runtime service is required.

## Routine commands

```sh
docker compose -p boxen -f deploy/compose.yaml ps
docker compose -p boxen -f deploy/compose.yaml logs --tail 100 web worker caddy
docker compose -p boxen -f deploy/compose.yaml run --rm --no-deps web verify
docker compose -p boxen -f deploy/compose.yaml stop caddy web worker
docker compose -p boxen -f deploy/compose.yaml up -d --no-build --pull never web worker caddy
```

`verify` reports database integrity, foreign-key errors, search mismatches and missing/corrupt originals; inspect its JSON as well as exit status. The owner System screen reports worker heartbeat, AI, disk and recent verified-backup health. Core readiness may remain healthy when AI or the worker is unavailable. Preserve volumes on shutdown: ordinary `stop` or `down` retains them; `down --volumes` destroys data and CA state and is not a routine command.

For upgrades, create a verified backup, retain the prior image and configuration, stop services, load/build the compatible image, run `init` explicitly if that release calls for a migration, then restart and verify. The current schema is `0002`. Do not assume down-migrations or automatic rollback exist. Restore a compatible backup with the corresponding prior image if needed.

Native long-running installations can supervise the exact `boxen web` and `boxen worker` commands from the README using their host service manager and a dedicated account. This repository currently provides Compose, not tested systemd unit files.
