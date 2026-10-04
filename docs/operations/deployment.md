# Docker deployment

Base Compose creates a separate installation. For the existing installation's
Tailscale address, data-preserving migration and daily container commands, see
[the Tailscale container runbook](container-tailnet.md).
See [volume/configuration specs](container-storage.md), [the architecture decision](../system-design/adrs/0010-container-deployment-and-ai-boundary.md) and [verification](../verification/containers.md).

## Images and platform

| Variable | Local default | Role |
| --- | --- | --- |
| `BOXEN_IMAGE` | `boxen:0.1.0` | Packaged UI/API, worker, init and maintenance |
| `BOXEN_CADDY_IMAGE` | `boxen-caddy:0.1.0` | HTTPS proxy with configuration included |
| `BOXEN_AI_IMAGE` | `boxen-ai:0.1.0` | Optional CPU launcher/libraries; no weights |

These are **not published Docker Hub repositories**. Set the references to an
owned namespace/release or digest when images are actually published. Base
Compose consumes images; source builds use overlays. No push or automatic updater
is configured. Docker Engine/Desktop and Compose are prerequisites. Linux amd64
is the initial tested platform; Docker Desktop, ARM64 and GPU are not thereby
qualified. Provisioning may need downloads; local runtime needs no public service.

## New installation

Run from the repository root. Copy [the example](../../deploy/.env.example) to
`deploy/.env` and edit it. For phones use your server's actual stable LAN IP:

```dotenv
BOXEN_HOST=192.0.2.10
BOXEN_BIND_ADDRESS=192.0.2.10
BOXEN_HTTPS_PORT=8443
BOXEN_ANONYMOUS_ACCESS=editor
```

Defaults deliberately publish loopback only. Host has no scheme/path/port;
Compose derives the exact origin from host and HTTPS port. Do not set a separate
`BOXEN_ORIGIN`. Bracket IPv6 addresses. Bind `0.0.0.0` means all interfaces;
retain one exact reachable host. Prefer a specific trusted-LAN interface.
Anyone who can connect gets the selected anonymous permissions. No router/WAN
port forwarding.

Build local images; installers run in builds, not on the host:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.build.yaml config --quiet
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.build.yaml build web caddy
```

With published/preloaded images, skip building; pull at provisioning time or use
`docker image load` for disconnected transfer. Then initialize and start:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps --pull never init
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml up -d --no-build --pull never --wait web worker caddy
```

Keep init's printed one-time token private; its Docker log driver is disabled.
Web startup does not silently initialize/migrate. Anonymous `editor` permits
box creation immediately; use `/setup` and the token to create an owner for
administration. `viewer` is read-only; `off` requires local accounts.

Open **HTTPS** at the chosen host and port on both host and phone. Localhost on a
phone means the phone. Permit the chosen port from your LAN in the host firewall;
guest-Wi-Fi isolation can still block access. No HTTP/API, Caddy administration
or model port is published.

## Local HTTPS and camera

Caddy uses its own CA without public ACME/DNS and does not install host trust.
Inspect the expected local certificate/address before accepting a browser
warning through its normal flow, where supported. Optionally install the
verified public CA for warning-free access. Camera permission is a separate
browser/device step; accepting a certificate does not grant it. Physical
Android/Brave behavior is not proven by desktop synthetic-camera tests.

Export **only the public root**, never private keys:

```sh
mkdir -p .local/boxen-trust
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt .local/boxen-trust/root.crt
openssl x509 -in .local/boxen-trust/root.crt -noout -subject -fingerprint -sha256
curl --fail --cacert .local/boxen-trust/root.crt https://192.0.2.10:8443/api/v1/health/ready
```

Use your configured URL. Check the fingerprint through a trusted host console
before importing trust. Preserve the CA volumes. Do not distribute the complete
Caddy volume or disable TLS/browser security globally.

## Separate local model container

Base deployment works without AI. Provision a checksum-pinned profile using the
[model guide](models.md). Set `BOXEN_AI_PROFILE=qwen3-vl-2b-q4-cpu` in
`deploy/.env` for the existing CPU profile. No runtime model download occurs.

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.ai-local.yaml -f deploy/compose.ai-build.yaml build boxen-ai
```

Import a complete existing profile using its actual source path. Only this
explicit `model-import` tool runs as container root with CHOWN/DAC_OVERRIDE and
read/write models, with networking disabled. Normal runtime stays non-root with
all capabilities dropped and read-only models. The importer verifies hashes,
refuses overwrites, assigns the new tree to UID/GID10001 and leaves the source
read-only. It shares only the selected project's model volume, not inventory.

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.ai-local.yaml run --rm --no-deps --pull never --volume /absolute/provisioned/qwen3-vl-2b-q4-cpu:/source:ro model-import
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.ai-local.yaml up -d --no-build --pull never web worker caddy boxen-ai
```

AI has no inventory or session-secrets mount and no published port. Loading
weights may take time; manual inventory stays usable. Defaults are
`BOXEN_AI_THREADS=8`, `BOXEN_AI_CPUS=8`, `BOXEN_AI_MEMORY=8g`; adjust to the
host/model. These are not speed guarantees. One worker/inference slot is
supported. Use this overlay consistently on later commands.

## Optional remote vision server

Use `compose.ai-remote.yaml` **instead of** local AI. See the precise
[endpoint contract](remote-ai.md). Remote mode explicitly adds outbound routing
to web/worker. Requested analysis sends a resized photo there; the UI discloses
this. No cloud fallback exists and manual inventory stays local.

```dotenv
BOXEN_AI_PROFILE=qwen3-vl-2b-q4-cpu
BOXEN_AI_BASE_URL=https://your-inference-host:8443
BOXEN_AI_PROFILES_DIR=/absolute/private/remote-profiles
```

Place metadata at `<profiles-dir>/<profile>/manifest.json`, readable by UID10001.
Weights are not required. Hashes are operator-reported, not remotely attested.
Optional `compose.ai-remote-auth.yaml` and `compose.ai-remote-ca.yaml` use
`BOXEN_AI_API_KEY_SOURCE` and `BOXEN_AI_CA_SOURCE` host file paths. Never put
credential values in .env, URLs, images or Git.

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.ai-remote.yaml config --quiet
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml -f deploy/compose.ai-remote.yaml up -d --no-build --pull never web worker caddy
```

HTTPS verification is enabled. Trusted-LAN plain HTTP requires explicit
`BOXEN_AI_ALLOW_INSECURE_HTTP=true`; photos/prompts/tokens then travel unencrypted.
Custom CA trust does not disable verification. Drain/cancel pending analyses
before changing endpoint/model; do not reuse profile IDs for different artifacts.
Stop an old local AI container when switching away from it.

## Operations and release

Add selected AI overlays consistently to these base commands:

```sh
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml logs --tail 100 web worker caddy
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml run --rm --no-deps --pull never web verify
docker compose --env-file deploy/.env -p boxen -f deploy/compose.yaml stop
```

Read integrity JSON as well as exit status. Ordinary stop/down preserves volumes.
**Never use down --volumes as an ordinary stop/upgrade.** The test harness removes
only its own uniquely named disposable project. See [storage](container-storage.md)
and [recovery](recovery.md) before upgrades/migration; the current schema is 0003.
Authentication upgrades require the same offline initialization procedure.
See [authentication setup](../help/authentication.md) for the protected core
administrator, password pepper, OIDC provider files and the optional OAuth
network overlay, and [administration](../help/administration.md) for recovery.

For a future Docker Hub release: choose the owned namespace, build/test each
claimed architecture, tag app/proxy/optional AI, record immutable digests and
scan results, and publish only with explicit authorization. Ship Compose,
.env.example, model source locks and runbooks. Retain prior images and backups.
Do not claim ARM/GPU support from a manifest alone. Docker's
[multi-platform guidance](https://docs.docker.com/build/building/multi-platform/)
describes the build mechanism, not application qualification.
