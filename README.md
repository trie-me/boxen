# Boxen

Boxen is a local box inventory app: photographs, Markdown descriptions, searchable contents, QR lookup and printable PDF labels. SQLite and local media hold your data. Optional local vision AI proposes items for human review; the core app works without a model or internet connection after installation.

Deployment addresses, host paths and Tailscale names in this repository are
examples. Replace them with your installation's private settings. Inventory,
credentials, certificates, model weights and local deployment files are excluded
from the repository; certificate fingerprints must come from your own host.

Photos collectively represent the items assigned to a box: packed contents, staged items, close-ups or reference views all work. The container need not appear. **Analyze all photos** queues independent analyses into one shared review. Review the item chips, remove unwanted suggestions with ×, add missing items, then **Accept items** to save the edited set together. Tap a chip for quantity/source details or to link repeated views to an existing item without counting its quantity twice. Completed photo analyses are remembered across navigation and devices; **Analyze again** requires confirmation. See the [AI repair evidence](docs/verification/ai-photo-collection.md) for actual timings and limitations and [chip-set design](docs/system-design/adrs/0007-chip-set-review.md) for review semantics.

Anonymous **editing** is enabled by default: create boxes, add contents and photos, and print labels without creating an account. Set `BOXEN_ANONYMOUS_ACCESS=viewer` for read-only access or `off` to require accounts. Administrative functions, backups, user management and irreversible purge require a local owner. Anyone who can reach the server gets the selected anonymous permissions; use a trusted network, never public port forwarding.

Use **tags** in the box editor for reusable labels such as `fragile` or `camping`.
Use **Collections** (also reachable from Your boxes on phones) for named groups
such as `Office move`. A box can belong to several collections. Each collection
shows combined contents grouped by source box or item name, with item filters,
quantities, units and links back to the original boxes. Nothing is copied,
merged or totaled; unknown quantities remain unknown. Removing membership or
deleting a collection preserves the boxes, photos and inventory. Search includes
tags and collection names, and both Your boxes and Search have exact filters.

Use **Pin label for printing** on box cards, search results or box details to
build a print list. Open **Print list (N)** in the header to remove labels and
prepare one PDF. Pins are saved in this browser for the current account;
**Pin all loaded boxes** adds the currently loaded results without duplicates.
A collection’s **Print collection labels** action prints every member, including
archived boxes, without changing your pins. Each label includes the box's current
collection names when it has any.
Multiple collections appear alphabetically beneath the box name; long lists
are shortened with an ellipsis to preserve QR and code readability.
Batch PDFs use US Letter,
4 × 2-inch labels in a 2 × 5 grid (Avery 5163/8163 layout), up to 500 labels per
PDF. Choose a starting position for a partly used sheet and adjust alignment
if needed. Print at **100% / actual size**, portrait and single-sided; test on
plain paper against your stock first. See [batch printing details and verification](docs/verification/batch-label-printing.md).

Search also offers contextual typeahead. Enter `BX-` and at least two code
characters (for example `BX-7K`) for matching boxes. Other text of at least two
letters/numbers suggests items, tags and collections, with the source box shown
for items. Use arrow keys and Enter, or tap a suggestion. Enter without choosing
one still searches all box names, descriptions and contents. Suggestions respect
the current filters and run entirely locally.
See [organization design](docs/system-design/adrs/0008-tags-and-collections.md).

The [system design](SYSTEM_DESIGN.md) is the authoritative specification; historical delivery statements in that baseline are not implementation evidence. See [implementation status](docs/verification/IMPLEMENTATION_STATUS.md) and [deployment evidence and gaps](docs/verification/deployment.md) for what has actually been checked.

## Authentication and help

Open **Help and setup** (`/help`) for the complete installation, configuration,
authentication, inventory, AI and recovery guides. Help is available before login.
The first owner is the protected **core system administrator**: setup suggests
`admin`, requires a unique password and provides no shared factory credential.
That account cannot be disabled, demoted or linked to OAuth. Local passwords use
salted Argon2id with a separate installation pepper; preserve its private file.

**System → Users** manages accounts and roles. **System → Authentication** manages
provider identity links and session revocation, and shows sign-in history.
Optional OIDC sign-in uses authorization code with PKCE and explicit issuer/subject
bindings to local users. Register your own provider client and configure its
private secret on the host; no provider is enabled automatically.
See [authentication setup](docs/help/authentication.md),
[administration and account recovery](docs/help/administration.md), and the
[implementation verification](docs/verification/authentication-store.md).

## Native quickstart

The verified platform is Linux with a local filesystem, CPython **3.13**, Node **24**, `uv` and pnpm **11.19.0**. The backend uses POSIX file locks; native macOS has not been qualified and native Windows is not supported. Use your existing tool manager; these steps do not globally install, upgrade, remove or prune runtimes. Dependency installation needs network access or preprovisioned caches. First enter **your actual Boxen checkout**, not another project's frontend directory. Install/build in a fail-fast subshell:

```sh
(
  set -eu
  test -f pyproject.toml && test -f frontend/package.json || {
    echo 'Run this from the Boxen repository root.' >&2
    exit 1
  }
  python3.13 --version
  node -e 'if (process.versions.node.split(".")[0] !== "24") process.exit(1)'
  test "$(pnpm --version)" = '11.19.0'
  uv sync --frozen --python 3.13
  pnpm --dir frontend install --frozen-lockfile
  pnpm --dir frontend build
)
```

If that block fails, stop and resolve the reported prerequisite; do not continue into startup. For an **existing installation**, retain its `BOXEN_DATA_DIR`—do not initialize a different directory. For a new installation, choose one data directory, then start:

```sh
export BOXEN_ENV=development
export BOXEN_ORIGIN=http://127.0.0.1:8000
export BOXEN_DATA_DIR="$PWD/.local/boxen/data"
# Optional: require an account instead of anonymous editing.
# export BOXEN_ANONYMOUS_ACCESS=off
.venv/bin/boxen init
.venv/bin/boxen web --host 127.0.0.1 --port 8000
```

The UI build is served by the backend at <http://127.0.0.1:8000>. **New box is immediately available without sign-in.** Keep the one-time token printed by `init` private and use `/setup` when you need an administrator. Choose a unique passphrase of at least 12 characters. The token file is removed and owner setup closes after successful creation. Re-running `init` preserves existing setup state; it is not an account-reset command.

First-owner setup requires the **host's one-time token**, not the new account's
password. If the original output was missed, read `secrets/setup-token` privately
inside the configured data directory on the host. Do not share it in chat. Login
opens setup until the first owner exists; afterward it uses that local account.
Setup/login now show rejected fields inline and retain entered values for retry.
Non-password fields trim accidental surrounding whitespace; passwords do not.

### Phones and other devices on your LAN

Stop the existing web process, retain the same data directory, and bind to the server's actual LAN address. For example, if this computer owns `192.0.2.10`:

```sh
export BOXEN_ENV=development
export BOXEN_ORIGIN=http://192.0.2.10:8000
export BOXEN_ANONYMOUS_ACCESS=editor
.venv/bin/boxen web --host 192.0.2.10 --port 8000
```

Open **http://192.0.2.10:8000** on the computer and phones on the same trusted network. Use the actual IP belonging to your host; `127.0.0.1` on a phone means the phone. The CLI also replaces an old loopback HTTP origin with a concrete `--host`/`--port` automatically. It prints the browser URL, data directory and anonymous mode at startup. Firewall rules must permit this port from your LAN; guest Wi-Fi/client isolation can block device-to-device connections. Do not create a router/WAN port forward.

For an all-interface bind, keep one explicit browser origin:

```sh
.venv/bin/boxen web --host 0.0.0.0 --port 8000 --origin http://192.0.2.10:8000
```

LAN HTTP supports creation/editing, image uploads, searching, labels, typed QR codes and uploaded QR images. Traffic is unencrypted: use it only on a trusted LAN, and use HTTPS before sending sensitive inventory or administrator credentials over a shared network. **Live in-browser camera scanning needs trusted HTTPS** because of browser security rules; photo/QR uploads remain available over HTTP. See the [LAN HTTPS setup](docs/operations/deployment.md#lan-https) when you want live scanning. Production mode continues to require HTTPS.

On phones, **Scan → Live camera → Take QR photo** requests the device's native
camera/photo picker and reads the selected image locally, including over HTTP.
The exact picker depends on the phone/browser; it is not continuous video scanning.
**Upload QR image** uses the same local decoding path. Image/decoder failures and
timeouts are visible, cancellable and retryable, including reselecting the same
file. Neither path sends the photo to a decoding service.

In another terminal, from the same repository, export the same three settings and start the worker:

```sh
export BOXEN_ENV=development
export BOXEN_ORIGIN=http://192.0.2.10:8000 # Match your chosen web URL; use loopback for host-only access.
export BOXEN_DATA_DIR="$PWD/.local/boxen/data"
.venv/bin/boxen worker
```

Use matching configuration in every process, including `BOXEN_ANONYMOUS_ACCESS` if changed. Stop each foreground process with Ctrl-C. The worker runs backups, maintenance and optional AI jobs. Automated backups begin only after an active owner exists. Do not use a network share for SQLite or commit the data directory.

The build command above is the simplest same-origin workflow. A separate Vite dev server needs its browser origin configured consistently; merely opening port 5173 with an 8000 origin configured will fail mutation-origin checks.

## Production configuration with local HTTPS

Docker Engine and Compose are required. Copy `deploy/.env.example` to
`deploy/.env` and set `BOXEN_HOST` and `BOXEN_BIND_ADDRESS` to your server's LAN
address for phone access. Defaults are loopback-only. The public origin is
derived from that host and `BOXEN_HTTPS_PORT` (8443 by default).

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.build.yaml config --quiet
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.build.yaml build web caddy
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps --pull never init
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never --wait web worker caddy
```

The app image serves UI/API and runs the worker separately. Local model execution
has its own optional container/read-only model volume; an explicitly configured
remote vision endpoint is also supported. Base Compose needs images only and is
ready for future Docker Hub image references; nothing has been published yet.
Skip building when using preloaded/released images.

Follow the [Docker deployment guide](docs/operations/deployment.md),
[volume/configuration specs](docs/operations/container-storage.md) and
[remote-AI contract](docs/operations/remote-ai.md). Application data and local CA
state persist in named volumes. Starting this stack creates a separate inventory;
it does not migrate your native installation. Keep init's setup token private.
The UI works anonymously without initial owner setup. Review the local certificate
warning or install the verified CA; camera permission remains browser-controlled.

## Operations

Existing installations need the explicit **0003** schema upgrade for the authentication
store (including the earlier tags and collections migration). Keep a verified pre-upgrade backup, stop web and worker processes,
then run `.venv/bin/boxen init` with the installation's existing configuration
and data directory before restarting them. Do not select a new data directory.
Startup checks schema compatibility; it does not silently migrate a running
database. Old 0001 backups remain verifiable and are upgraded only in a staging
copy during an offline restore. See the recovery runbook below.

- [Deployment, configuration, CA trust and service commands](docs/operations/deployment.md)
- [Tailscale containers: migration, restart, verification and rollback](docs/operations/container-tailnet.md)
- [Daily backups, offline restore/quarantine and disconnected transfer](docs/operations/recovery.md)
- [Optional local model provisioning and disabled behavior](docs/operations/models.md)

The project-local Qwen3-VL CPU profile has a real image-to-reviewed-inventory smoke test; see [AI evidence and limitations](docs/verification/ai-local-cpu.md). It is not broadly accuracy-qualified. Current operational limits include no automatic backup pruning and no completed physical phone/CA/camera or printer qualification. Non-root Compose startup, trusted local HTTPS, anonymous access and protected administration have been checked with disposable data. Full disconnected transfer and Compose restore rehearsals remain outstanding; native restore and network-disabled production-image workflows are covered separately.
