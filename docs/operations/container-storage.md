# Container storage and configuration specification

The Compose deployment is separate from an existing native installation. Do not
start an empty Docker volume and expect it to contain native inventory. No
automatic import, migration, host trust modification or Docker Hub push occurs.

## Volumes

| Volume/mount | Container path | Users/access | Contents and recovery |
| --- | --- | --- | --- |
| `boxen-data` | `/var/lib/boxen` | Web, worker, init/CLI; UID/GID `10001:10001`, read/write | Active `data/` plus restore quarantines. Preserve the entire volume. |
| `boxen-models` (local AI only) | `/models` | AI, web and worker; read-only during execution | Profile manifests, weights, projector, executable, libraries and licenses. Provision explicitly. Not included in inventory backups. |
| Remote profile directory | `/models` | Web/worker, read-only | Profile metadata only; no model weights required. Protect configuration against unauthorized replacement. |
| `caddy-data` | `/data` | Proxy UID/GID `10001:10001`, read/write | Private local CA keys and certificates. Preserve across upgrades to avoid changing the installation's CA. |
| `caddy-config` | `/config` | Proxy, read/write | Proxy state. Preserve with `caddy-data`. |
| Optional secret/CA files | `/run/secrets/...` | Web/worker, read-only and readable by UID 10001 | Remote API token or public CA bundle. Never bake into an image, Git, a URL or an environment value. |
| Temporary memory filesystem | `/tmp` | Each container separately | Ephemeral scratch; not a persistence or backup location. |

The active application tree is:

```text
/var/lib/boxen/
  data/
    db/boxen.sqlite3       # structured inventory, users, jobs, FTS search
    db/boxen.sqlite3-wal   # SQLite manages WAL and SHM beside the DB
    db/boxen.sqlite3-shm
    db/*.lock             # process/maintenance coordination
    media/originals/      # authoritative uploaded photos
    media/display/        # rebuildable display images
    media/thumbnails/     # rebuildable thumbnails
    media/staging/        # in-progress uploads
    secrets/              # session key and initial setup token, if unused
    backups/              # verified snapshots; same-disk copies by default
    tmp/
    models/               # native legacy default; unused with /models configured
  data.quarantine-.../    # retained by offline restore
```

**Do not bind-mount only the `.sqlite3` file.** WAL/SHM and locking must share its
directory. Do not split originals and DB into unrelated backup schedules. Use a
local filesystem with POSIX locking, not a network share or cloud-sync folder.
Run exactly one worker per installation; its file lock rejects duplicates.

Named volumes get the expected ownership from the image. For a bind mount,
create a dedicated installation directory first and assign that directory to
UID/GID 10001. Do not recursively change ownership of a home directory or an
existing native installation. Files provisioned with private host-user modes
must be copied into a dedicated container-owned model volume; mounting them
unchanged under another UID will fail verification. Do not solve this by
making secrets/models world-writable or running the application as root.

The optional `model-import` service is an explicit provisioning exception: no
network, only the destination model volume read/write and the selected source
profile read-only. Container root with CHOWN/DAC_OVERRIDE assigns the newly
imported files to UID10001. It is not a long-running service and never receives
the application data volume.

Data capacity is workload-dependent: originals + derivatives + verified backups
+ room for a complete restore staging copy and retained quarantine. Production
reserves at least 2 GiB and 5% free disk. The existing 2B CPU model has about
1.55 GB of weights/projector, plus its native executable/libraries. Weights do
not belong in the ordinary application image or its backup.

## Application settings

Flat TOML via `BOXEN_CONFIG_FILE` is optional; recognized `BOXEN_*` environment
values override it. Paths refer to paths **inside the container**. Unknown
`BOXEN_*` variables fail startup, so do not inject the entire Compose `.env` as
an application `env_file`: some variables are Compose interpolation only.

| Setting | Default / use |
| --- | --- |
| `BOXEN_ENV` | Compose `production`; requires an HTTPS browser origin. |
| `BOXEN_ORIGIN` | Exact public URL including port, no path/trailing slash. Must match proxy host and published port. |
| `BOXEN_ANONYMOUS_ACCESS` | `editor`; alternatives `viewer` and `off`. Anonymous users never administer accounts/backups. |
| `BOXEN_DATA_DIR` | Compose `/var/lib/boxen/data`; retain the same path across all services and CLI commands. |
| `BOXEN_DATABASE_PATH` | Default `$BOXEN_DATA_DIR/db/boxen.sqlite3`; must remain inside the data directory. Normally leave unset. |
| `BOXEN_SESSION_KEY_FILE` | Default `$BOXEN_DATA_DIR/secrets/session.key`; do not replace on recreation. |
| `BOXEN_PASSWORD_PEPPER_FILE` | Default `$BOXEN_DATA_DIR/secrets/password.pepper`; private 32-byte password pepper, separate from the session key and excluded from inventory backups. Preserve a protected recovery copy. |
| `BOXEN_OAUTH_PROVIDERS_FILE` | Optional provider JSON path, read at web startup. See [authentication setup](/help/authentication) and `deploy/compose.oauth.yaml` for private mounts and outbound provider access. |
| `BOXEN_AI_MODE` | `local` default, or explicit `remote`. No configured profile means AI unavailable without affecting core inventory. |
| `BOXEN_AI_PROFILE` | Provisioned profile directory name; empty/unset disables model use. |
| `BOXEN_AI_MODELS_DIR` | Native defaults to `$BOXEN_DATA_DIR/models`; AI Compose overlays use `/models`. |
| `BOXEN_AI_BASE_URL` | Local `http://boxen-ai:8080`; remote is an explicitly configured server root, without the adapter's `/v1` suffix. |
| `BOXEN_AI_API_KEY_FILE` | Optional remote-only bearer token file. No token value in `.env`. |
| `BOXEN_AI_CA_FILE` | Optional remote-only CA PEM bundle; default uses normal TLS verification. |
| `BOXEN_AI_ALLOW_INSECURE_HTTP` | `false`; set true only for a deliberately trusted remote LAN HTTP endpoint. Does not disable HTTPS certificate checks. |
| `BOXEN_AI_TIMEOUT` | 300 seconds maximum, including bounded truncation retry. Supported 1–300. |
| `BOXEN_WORKER_SLOTS` | Exactly `1`; multiple API/worker replicas are not the deployment target. |
| `BOXEN_MAX_UPLOAD_BYTES` | 25 MiB default; proxy independently caps request bodies at 26 MB. Coordinate both if changing upload size. |
| `BOXEN_MAX_IMAGE_PIXELS` | 50 million default, decoded-image bound. |
| `BOXEN_DISK_RESERVE_BYTES` / `BOXEN_DISK_RESERVE_PERCENT` | 2 GiB / 5%; production disallows lower values. |
| `BOXEN_LOG_LEVEL` | `INFO`. Do not log image bodies, credentials or raw remote error responses. |
| `BOXEN_BACKUP_RETENTION` | 14, but automatic pruning is **not implemented**. This does not delete old backups. |

Not every application knob is interpolated by the supplied Compose file. For
an advanced setting, add the same `environment` entry to web, worker and
administrative services in a local Compose override. Check the merged output
with `docker compose config` before starting. Do not put secret values there.

## Backups, upgrades and moving hosts

Container recreation and ordinary `docker compose down` preserve named volumes.
`down --volumes`, `volume rm` and volume pruning can destroy data; they are not
normal stop/upgrade commands. A Docker image checkpoint is not a data backup.

Use Boxen's verified backup workflow for a consistent DB/original-photo snapshot,
then copy it to protected separate storage. Inventory backups intentionally omit
session secrets, model files and TLS CA state. Full host recovery also requires
the complete stopped application volume, CA volumes, configuration and selected
model profile. Keep their permissions; full-volume archives contain credentials.

Before an upgrade: verified backup, retain prior image/config, stop services,
run explicit `init` only when schema upgrade is required, restart and verify.
Do not run migrations concurrently with web/worker, delete WAL files, or assume
down-migrations exist. See [recovery procedures](recovery.md). A backup on the
same volume protects against logical mistakes, not disk loss.

The packaged local model mount is outside the application tree; restore leaves
it alone. Preserve the matching model profile independently when rolling back.
Do not modify a profile's weights or metadata while web/worker/inference are
running. Drain/cancel outstanding analyses before switching remote endpoints.
