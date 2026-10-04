# Container configuration reference

Start with the [container quick start](deployment.md). This page covers every Boxen setting exposed by the supplied Compose files, all application settings and persistent storage.

## How configuration works

There are two layers:

1. **Compose inputs** in `deploy/.env` choose images, bindings and optional mounts. Compose substitutes these into the YAML. Only explicitly mapped values reach a container.
2. **Application settings** are the `BOXEN_*` variables inside web, worker or a CLI container. Advanced settings require an explicit Compose override; adding them to `deploy/.env` alone does not configure the app.

Do **not** add `env_file: deploy/.env` to a service. The file includes Compose-only inputs such as image names, which the application rejects as unknown settings. Do not put passwords, tokens or private keys in it.

The helper selects `deploy/.env` unless `BOXEN_ENV_FILE` points elsewhere. Relative `BOXEN_ENV_FILE` paths resolve from your current working directory. Exported shell values take precedence over matching values in the selected file, so unset stale `BOXEN_*` variables when an edit appears ineffective. Use `config --quiet` to validate or `config` to inspect the merged configuration privately.

```sh
./scripts/boxen-compose config --quiet
```

The helper is equivalent to:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.build.yaml "$@"
```

It does not automatically select optional overlays or initialize data. Extra `-f` files are applied in order. Relative paths **inside YAML** resolve against `deploy/`, the directory of the first Compose file; this differs from command-line file paths. See Docker's [merging rules](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/) and [variable precedence](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## Compose settings

### Base installation

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOXEN_IMAGE` | `boxen:0.1.0` | Shared app image for web, worker, init and maintenance. Built locally by the quick start. |
| `BOXEN_CADDY_IMAGE` | `boxen-caddy:0.1.0` | Local HTTPS proxy image, with its configuration included. |
| `BOXEN_HOST` | `localhost` | One browser hostname or IP, without scheme, port or path. Used for the TLS certificate and app origin. Use a DNS name for IPv6 clients. |
| `BOXEN_BIND_ADDRESS` | `127.0.0.1` | Host IP on which Docker publishes HTTPS. Use the host's LAN/Tailscale IP for other devices. `0.0.0.0` binds all IPv4 interfaces. |
| `BOXEN_HTTPS_PORT` | `8443` | Host HTTPS port mapped to container port 8443. The app origin is `https://HOST:PORT`. |
| `BOXEN_ANONYMOUS_ACCESS` | `editor` | `editor`: read/change inventory; `viewer`: read only; `off`: require an account. Anonymous users never administer the installation. |
| `COMPOSE_PROJECT_NAME` | `boxen` from YAML | Optional standard Docker Compose setting; changes container/network/volume names. `-p NAME` takes precedence. Changing it selects another installation. |
| `BOXEN_ENV_FILE` | `deploy/.env` in this checkout | Helper-only environment variable selecting the Compose input file. Set it when invoking `scripts/boxen-compose`, not inside `.env`. |

The image tags are local names, not published Docker Hub releases. You can choose your own local tags or preloaded image references. No automatic updater or image push is configured. Core settings in the YAML fix `BOXEN_ENV=production` and `BOXEN_DATA_DIR=/var/lib/boxen/data`; Compose derives `BOXEN_ORIGIN` from the host and port. Do not separately set those in `.env`.

### Local AI overlay

These settings take effect with `compose.ai-local.yaml`. Setting them alone does not enable AI.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOXEN_AI_IMAGE` | `boxen-ai:0.1.0` | CPU inference image. Build it with `compose.ai-build.yaml`; weights are separate. |
| `BOXEN_AI_PROFILE` | Required when overlay is selected | Directory name of the imported profile under `/models`; for example `qwen3-vl-2b-q4-cpu`. |
| `BOXEN_AI_THREADS` | `8` | CPU threads passed to the model launcher. |
| `BOXEN_AI_CPUS` | `8` | Docker CPU quota for the AI service. Match your host's capacity. |
| `BOXEN_AI_MEMORY` | `8g` | Docker memory limit for AI; must fit the model and runtime. |

The overlay supplies `BOXEN_AI_MODE=local`, `BOXEN_AI_BASE_URL=http://boxen-ai:8080` and `BOXEN_AI_MODELS_DIR=/models` to web/worker. No model port is published. Import a verified profile before starting; see [local model setup](deployment.md#separate-local-model-container).

### Remote AI overlays

Select `compose.ai-remote.yaml` instead of local AI. It sets remote mode, mounts profile metadata at `/models`, and gives web/worker outbound network access.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOXEN_AI_PROFILE` | Required | Profile metadata directory name; no model weights required on the Boxen host. |
| `BOXEN_AI_BASE_URL` | Required | Your explicitly selected remote server root. The adapter appends API paths; see the [endpoint contract](remote-ai.md). |
| `BOXEN_AI_PROFILES_DIR` | Required | Absolute existing host directory containing `<profile>/manifest.json`, mounted read-only. |
| `BOXEN_AI_ALLOW_INSECURE_HTTP` | `false` | Permit remote plain HTTP only when explicitly set to `true`. HTTPS verification remains enabled. |
| `BOXEN_AI_API_KEY_SOURCE` | Required with `compose.ai-remote-auth.yaml` | Absolute host path to the bearer-token file, mounted as `/run/secrets/boxen_ai_api_key`. |
| `BOXEN_AI_CA_SOURCE` | Required with `compose.ai-remote-ca.yaml` | Absolute host path to a public PEM CA bundle, mounted as `/run/secrets/boxen_ai_ca`. |

Mounted files must exist and be readable by UID 10001. File-backed Compose secrets retain host-file permissions; choosing a secret mount does not fix ownership. The auth/CA overlays set the corresponding application `_FILE` variables. Credentials are file contents, never environment values. Remote requests send resized photos only when analysis is requested.

### OIDC overlay

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOXEN_OAUTH_CONFIG_DIR` | Required with `compose.oauth.yaml` | Absolute existing private host directory containing `providers.json` and referenced client-secret files. Mounted read-only at `/run/boxen-oauth`. |

The overlay sets `BOXEN_OAUTH_PROVIDERS_FILE=/run/boxen-oauth/providers.json` for web and enables its outbound provider connections. Keep secrets private and readable by UID 10001. The [authentication guide](../help/authentication.md#configure-an-oidc-provider) describes provider JSON, client registration and identity binding.

### Extended Tailscale overlay

The base stack already supports a single Tailscale address. `compose.tailnet.yaml` adds IPv6 and redirects from a previous LAN address; use the [Tailscale runbook](container-tailnet.md) for the complete setup.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BOXEN_HOST` | Required by this overlay | Canonical Tailscale DNS name used in links and the app origin. |
| `BOXEN_BIND_ADDRESS` | Required by this overlay | Host Tailscale IPv4 address. |
| `BOXEN_TAILNET_IPV6` | Required | Host Tailscale IPv6 address for additional published sockets. |
| `BOXEN_LEGACY_HOST` | Required | Previous LAN IPv4 address, still owned by the host, for redirect listeners. |
| `BOXEN_HTTPS_PORT` | `8443` | HTTPS port on the tailnet and old LAN listeners. |
| `BOXEN_HTTP_PORT` | `8000` | HTTP redirect port on both networks. |

This overlay publishes more ports than the base setup and uses `Caddyfile.tailnet`. The dedicated `scripts/boxen-tailnet` helper selects that deployment's private env file, project and local-AI overlays; the generic quick start uses `scripts/boxen-compose` instead.

## Compose files and service limits

| File in `deploy/` | Purpose |
| --- | --- |
| `compose.yaml` | Images, core services, private network and persistent volumes. |
| `compose.build.yaml` | Source builds for app/proxy; included by `scripts/boxen-compose`. |
| `compose.ai-local.yaml` | Local AI service, model volume and explicit `model-import` tool. |
| `compose.ai-build.yaml` | Source build for the AI image. |
| `compose.ai-remote.yaml` | Remote endpoint settings, metadata mount and outbound network. |
| `compose.ai-remote-auth.yaml` | Remote bearer-token file mount. |
| `compose.ai-remote-ca.yaml` | Remote custom-CA file mount. |
| `compose.oauth.yaml` | OIDC config mount and web-only outbound network. |
| `compose.tailnet.yaml` | Canonical tailnet address, IPv6 and legacy-address redirects. |

Web, worker and init each have a 2-CPU quota, 2 GiB memory limit, 160-process limit and 128 MiB temporary filesystem. They have a 330-second shutdown grace period. Caddy has a 16 MiB temporary filesystem. Runtime containers use UID/GID 10001, read-only roots, no added capabilities and no privilege escalation. App, worker and proxy logs rotate at 10 MB with three files; init logging is disabled because it prints the setup token. Exactly one worker is supported.

Change resource limits with an explicit override if your host needs different allocations; these are YAML settings, not additional `.env` variables. Caddy's request body limit is 26 MB, independently of the application's 25 MiB upload limit.

## Application settings

These are all fields accepted by the backend's `Settings` model. **Only a subset is mapped by the supplied Compose files.** Paths below are inside containers. Unless listed as a Compose input above, configure a setting through an [advanced override](#advanced-overrides).

### Core, authentication and storage

| Setting | Default and constraints |
| --- | --- |
| `BOXEN_ENV` | `production`; also accepts `development` and `test`. Production requires HTTPS and minimum disk reserves. |
| `BOXEN_ORIGIN` | Native default `https://boxen.local`; Compose derives `https://HOST:PORT`. Exact browser origin: no path, trailing slash, query, credentials or wildcard host. |
| `BOXEN_ANONYMOUS_ACCESS` | `editor`, `viewer` or `off`. |
| `BOXEN_DATA_DIR` | Native `/var/lib/boxen`; Compose `/var/lib/boxen/data`. Keep consistent across web, worker and all maintenance commands. |
| `BOXEN_DATABASE_PATH` | `<data-dir>/db/boxen.sqlite3`; must stay under the data directory. Usually leave unset. |
| `BOXEN_SESSION_KEY_FILE` | `<data-dir>/secrets/session.key`; private installation secret, at least 32 bytes. Preserve across recreation. |
| `BOXEN_PASSWORD_PEPPER_FILE` | `<data-dir>/secrets/password.pepper`; separate private 32-byte secret used by password verification. Preserve a protected recovery copy. |
| `BOXEN_OAUTH_PROVIDERS_FILE` | Unset; optional provider JSON read at web startup. Requires a corresponding mount and network access. |
| `BOXEN_FRONTEND_DIR` | Packaged `boxen/static` directory; leave unset to serve the embedded UI. Primarily useful for native development. |

### Limits and operations

| Setting | Default and constraints |
| --- | --- |
| `BOXEN_MAX_UPLOAD_BYTES` | `26214400` (25 MiB); supported range 1 byte–100 MiB. Increasing it also requires coordinating Caddy's request-body limit. |
| `BOXEN_MAX_IMAGE_PIXELS` | `50000000`; supported range 1–100,000,000 decoded pixels. |
| `BOXEN_WORKER_SLOTS` | `1`; other values are rejected. |
| `BOXEN_DISK_RESERVE_BYTES` | `2147483648` (2 GiB); production rejects lower values. |
| `BOXEN_DISK_RESERVE_PERCENT` | `5`; production rejects lower values. Both free-space requirements apply. |
| `BOXEN_LOG_LEVEL` | `INFO`; currently accepted by configuration but not wired into runtime logging. Changing it does not alter log verbosity. |
| `BOXEN_BACKUP_RETENTION` | `14`; reserved setting. **Automatic pruning is not implemented** and this value does not delete backups. |

### Analysis

| Setting | Default and constraints |
| --- | --- |
| `BOXEN_AI_MODE` | `local` or explicit `remote`. No profile means AI is unavailable without affecting inventory. |
| `BOXEN_AI_PROFILE` | Unset; provisioned profile directory name. Empty also disables model use; no path separators allowed. |
| `BOXEN_AI_MODELS_DIR` | `<data-dir>/models`; AI Compose overlays set `/models`. |
| `BOXEN_AI_BASE_URL` | `http://boxen-ai:8080`; local mode permits only loopback/private `boxen-ai` HTTP. Remote mode requires explicit configuration and HTTPS unless opted out. No credentials, query or fragment. |
| `BOXEN_AI_API_KEY_FILE` | Unset; optional remote-only bearer-token file. |
| `BOXEN_AI_CA_FILE` | Unset; optional remote-only public CA bundle. Normal TLS verification is the default. |
| `BOXEN_AI_ALLOW_INSECURE_HTTP` | `false`; explicit opt-in to remote HTTP. Does not disable HTTPS certificate verification. |
| `BOXEN_AI_TIMEOUT` | `300` seconds; supported 1–300, including the bounded larger-output retry. |

## Advanced overrides

For example, to reduce the upload limit consistently, create the ignored file `deploy/compose.local.yaml`:

```yaml
x-extra-environment: &extra-environment
  BOXEN_MAX_UPLOAD_BYTES: "10485760"
services:
  init:
    environment: *extra-environment
  web:
    environment: *extra-environment
  worker:
    environment: *extra-environment
```

Use it on **every** relevant command:

```sh
./scripts/boxen-compose -f deploy/compose.local.yaml config --quiet
./scripts/boxen-compose -f deploy/compose.local.yaml up -d --no-build --pull never --wait web worker caddy
```

Compose merges the environment map with the base values; this example changes only the upload limit. Do not replace persistent volume paths casually. An override requiring new host files also needs mounts and permissions for UID 10001. You can keep a shell function with all selected `-f` options to avoid omitting one later.

The app also supports a flat TOML file selected by **`BOXEN_CONFIG_FILE`** (unset by default). Keys are lowercase field names, for example `max_upload_bytes = 10485760`. Mount that file read-only and explicitly pass its container path to each applicable service. Recognized application environment values override TOML, including values already supplied by Compose. Unknown fields or `BOXEN_*` variables fail startup.

## Volumes

With the default project name, Docker names volumes `boxen_boxen-data`, `boxen_caddy-data` and `boxen_caddy-config`. A different project name changes that prefix. Inspect the selected stack with `./scripts/boxen-compose config --volumes`.

| Volume or mount | Container path | Contents and access |
| --- | --- | --- |
| `boxen-data` | `/var/lib/boxen` | Web, worker and init/CLI read/write as UID 10001. Contains active `data/` and restore quarantines; preserve the entire volume. |
| `caddy-data` | `/data` | Proxy's private CA keys and certificates. Preserve so client trust survives updates. |
| `caddy-config` | `/config` | Persistent proxy state; keep with `caddy-data`. |
| `boxen-models` (local AI) | `/models` | Verified profile artifacts, weights, runtime and licenses. Read-only at runtime; writable only by explicit import. |
| Remote profiles directory | `/models` | Host-managed profile metadata, read-only in web/worker. |
| Optional remote token/CA files | `/run/secrets/...` | Read-only, readable by UID 10001. |
| Optional OIDC directory | `/run/boxen-oauth` | Read-only provider JSON and private client secrets, web only. |
| Temporary memory filesystems | `/tmp` | Separate per container, discarded on recreation. |

The application tree is:

```text
/var/lib/boxen/
  data/
    db/boxen.sqlite3       # inventory, users, jobs and search
    db/                   # SQLite WAL/SHM and coordination locks
    media/originals/      # normalized WebP uploads and unchanged legacy photos
    media/display/        # rebuildable derivatives
    media/thumbnails/
    media/staging/
    secrets/              # session key, password pepper, unused setup token
    backups/              # verified snapshots, on the same disk by default
    tmp/
    models/               # native default; unused with /models configured
  data.quarantine-.../    # retained by offline restore
```

**Do not mount only the SQLite file.** Its WAL/SHM and lock files must share the directory. Keep the DB and originals in consistent backups, on a local filesystem with POSIX locking, not a network share or cloud-sync directory.

Named volumes receive the expected ownership from the images. For a bind mount, create a dedicated directory and give only that directory to UID/GID 10001. Private installation secrets must not be accessible to other users. Do not fix permissions by recursively changing your home directory or running the application as root. Existing private model files should be copied through the explicit `model-import` tool, which leaves the source read-only and never mounts inventory.

Capacity must cover originals, derivatives, backups, a complete restore staging copy and retained quarantines, with the production free-space reserve left over. Model files and Docker build caches also consume disk space.

New uploads use WebP quality 85, a maximum 2,048-pixel longest edge and a 480-pixel thumbnail, preserving proportions without upscaling. The full-size display shares the stored WebP rather than duplicating it. These are fixed encoding defaults; upload byte/pixel limits still apply to incoming files before conversion. Existing photos and previous backups are not rewritten.

## Backups, upgrades and moving hosts

Normal container recreation, `stop` and `down` preserve named volumes. `down --volumes`, volume removal and pruning can destroy data. An image is not a data backup.

Inventory backups contain the database and original photos, but omit installation secrets, models and TLS state. Copy backups to protected separate storage; a backup on the same volume cannot survive disk loss. Preserve the password pepper separately for account recovery. Full host recovery needs the complete stopped application volume, CA volumes, configuration and selected model profile, with permissions intact. Full-volume archives contain credentials.

Follow the [upgrade sequence](deployment.md#backups-and-upgrades) and [recovery runbook](recovery.md). Do not migrate while web/worker are running, delete WAL files or assume schema downgrades exist. Models mounted outside the application tree are not changed by inventory restore. Stop/drain analysis before switching profiles or endpoints.
