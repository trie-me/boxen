# Native development

For everyday hosting, use the [container quick start](deployment.md). The native development path is tested on Linux with a local filesystem, Python **3.13**, Node **24**, `uv` and pnpm **11.19.0**. Native Windows is unsupported; native macOS has not been qualified. The backend uses POSIX file locks.

## Install and build

Run from the repository root with those runtimes already installed:

```sh
uv sync --frozen --python 3.13
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

The backend serves the built frontend at the same origin. A separate Vite server requires matching browser-origin configuration; simply opening port 5173 while configuring an 8000 origin will fail mutation checks.

## Start a development installation

Use a separate data directory for development. For an existing installation, retain its configured directory; changing it selects a different inventory.

```sh
export BOXEN_ENV=development
export BOXEN_ORIGIN=http://127.0.0.1:8000
export BOXEN_DATA_DIR="$PWD/.local/boxen/data"
export BOXEN_ANONYMOUS_ACCESS=editor
.venv/bin/boxen init
.venv/bin/boxen web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Keep the token from `init` private and use `/setup` to create the first administrator. In a second terminal, set the same environment and start the worker:

```sh
export BOXEN_ENV=development
export BOXEN_ORIGIN=http://127.0.0.1:8000
export BOXEN_DATA_DIR="$PWD/.local/boxen/data"
export BOXEN_ANONYMOUS_ACCESS=editor
.venv/bin/boxen worker
```

Stop each process with Ctrl-C. The worker runs backups, maintenance and optional analysis jobs. Automated backups begin after an active owner exists. Re-running `init` preserves setup state; it does not reset an account.

For LAN development, change the origin in both terminals to the server's actual address (for example `http://192.0.2.10:8000`) and use that address for `web --host`. HTTP traffic is unencrypted; use [native HTTPS](native-https.md) for shared networks and live browser camera scanning. Production requires HTTPS. Do not use a network share for SQLite.

## Checks

```sh
.venv/bin/python -m pytest backend/tests
.venv/bin/ruff check backend
.venv/bin/mypy backend/boxen
pnpm --dir frontend test
pnpm --dir frontend build
```

Real-model integration tests require the explicitly provisioned profile described in the [model guide](models.md). See the [configuration reference](container-storage.md#application-settings) for application settings and [recovery guide](recovery.md) before operating on an existing inventory.
