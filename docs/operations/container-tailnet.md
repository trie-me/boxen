# Boxen containers on Tailscale

Addresses and filesystem paths below are anonymized examples. Substitute your
own Tailscale DNS/IPs, previous LAN IP and checkout path before running commands.

This is the container equivalent of the
[native Tailscale operation](native-tailnet.md). The browser address stays
**https://boxen.example-tailnet.ts.net:8443**. Tailscale runs on the host; containers
do not receive its socket, credentials or privileged network access. Tailscale
Serve is not required. The existing Boxen CA can be retained during migration.

**Deployed on 2026-10-04:** web, worker, HTTPS proxy and local AI now run in
containers. The native services are stopped. Existing data, account secrets,
model profile and CA were copied and verified; the native directories remain as
pre-cutover rollback material. See [deployment evidence](../verification/container-tailnet.md).

## Daily commands

From `/path/to/boxen`, the wrapper selects the same project, private env
file and overlays on every invocation:

```sh
scripts/boxen-tailnet ps
scripts/boxen-tailnet restart
scripts/boxen-tailnet logs --tail 100 web worker caddy boxen-ai
scripts/boxen-tailnet stop
scripts/boxen-tailnet up -d --no-build --pull never --wait web worker caddy boxen-ai
```

The private settings file is `.local/boxen-container.env`; the Compose project is
`boxen-tailnet`. `BOXEN_TAILNET_ENV_FILE` can select another settings file without
changing that project. Containers use `restart: unless-stopped`. After a host
restart, Tailscale must have its configured addresses before published container
ports can bind; if necessary, use the `up` command above after Tailscale is ready.
The old `.local/boxen/app.toml` and native data directory are no longer the live
configuration or inventory. Use container commands and volumes for current work.

Only the proxy publishes ports: `8443` for HTTPS and `8000` for HTTP on the
Tailscale IPv4/IPv6 addresses and the previous LAN IP. HTTP and old LAN URLs
redirect reads to the canonical address; writes return `400`. Public certificate
downloads remain under `/trust/`. Web, worker and local AI use a private Docker
network, with no direct published ports or outbound Internet route.

Clients need Tailscale access and the existing local certificate trust. New
clients can follow [certificate setup](native-https.md). Changing the service to
containers does not change the browser origin, so existing cookies and pin lists
continue to use the same origin. Account permissions remain unchanged.

## Files and persistent storage

| File or volume | Purpose |
| --- | --- |
| `deploy/tailnet.env.example` | This host's example DNS name, bind addresses and local image tags |
| `deploy/compose.tailnet.yaml` | Specific host-interface bindings and proxy configuration |
| `deploy/Caddyfile.tailnet` | HTTPS, read redirects and isolated public certificate routes |
| `boxen-tailnet_boxen-data` | `/var/lib/boxen/data`: database, photos, backups, account/session secrets |
| `boxen-tailnet_boxen-models` | `/models`: checksum-verified local model and runtime, read-only during operation |
| `boxen-tailnet_caddy-data` | `/data/caddy`: certificates/private CA; `/data/boxen-public`: public files only |
| `boxen-tailnet_caddy-config` | Caddy configuration state |

Routine containers run as UID/GID `10001`, with read-only root filesystems and
dropped capabilities. Dedicated volumes hold writable state. Do not change the
ownership of the original native installation. Do not use `down --volumes`,
volume removal or pruning on this project. See [storage](container-storage.md)
and [recovery](recovery.md) for backup/restore requirements; inventory backups
exclude the password pepper, session key, TLS CA and model files.

## Build and validate

Prerequisites: Docker Engine, Compose, a working host Tailscale connection and
available specific bind addresses. This profile retains a previous LAN address;
set `BOXEN_LEGACY_HOST` to that IP. Check actual addresses with `tailscale ip` and
the DNS name with `tailscale status --json` before copying the example.

```sh
mkdir -p .local
cp deploy/tailnet.env.example .local/boxen-container.env
chmod 600 .local/boxen-container.env
# Edit addresses/image tags as needed before continuing.
scripts/boxen-tailnet config --quiet
scripts/boxen-tailnet build web caddy boxen-ai
```

The base IPv4 HTTPS binding and five overlay bindings combine using
[Compose's port merge rules](https://docs.docker.com/reference/compose-file/merge/).
Inspect the merged `ports` before starting. Do not add wildcard or public router
forwarding. Images are built locally; these tags are not published on Docker Hub.

For a new, empty installation, initialize once with `scripts/boxen-tailnet run
--rm --no-deps --pull never init`, keeping the printed setup token private, then
import the model using the [model import procedure](deployment.md#separate-local-model-container).
For an existing installation, use the stopped-data procedure below instead.

After a new CA is generated, export only its public root:

```sh
scripts/boxen-tailnet cp caddy:/data/caddy/pki/authorities/local/root.crt .local/boxen-root.crt
openssl x509 -in .local/boxen-root.crt -noout -fingerprint -sha256
```

The `/trust/` download is enabled only when a public copy is placed at
`/data/boxen-public/boxen-local-ca.crt`. Do not make the CA key directory a web
root. The migration below supplies the existing public certificate and page.

## Existing native installation: migration procedure

1. Build and test images while native Boxen stays available. Use a disposable
   Compose project and unused ports to check HTTPS, writes, PDF output, local AI
   and recreation persistence. Never initialize an empty replacement over the
   user's installation.
2. Confirm no analysis, maintenance or backup jobs are active. Save the native
   unit definitions, configuration and deployed frontend in a private rollback
   directory. Stop native web and worker before taking the final data copy.
3. Copy the complete stopped native data directory, including `db`, `media`,
   `backups` and `secrets`, into a private snapshot. Preserve the session key,
   password pepper, setup token and account records. Take an SQLite online-backup
   copy and verify integrity/foreign keys and table hashes. Keep the native tree
   untouched as a rollback source. The large `models` tree is imported separately.
4. Seed an **empty** dedicated `boxen-tailnet_boxen-data` volume with the snapshot
   under `data/`; assign only the new copy to UID/GID `10001`, retaining private
   modes. Refuse a nonempty destination. Do not mount only the SQLite file.
5. Import the existing provisioned model using `model-import` with its source
   mounted read-only. Verify copied hashes. Stop the native inference process
   before starting the new inference container to avoid duplicate memory usage.
6. Stop native Caddy; privately copy its entire storage directory into
   `boxen-tailnet_caddy-data` at `caddy/` and its **public-only** certificate/page
   directory into `boxen-public/`. Assign the new copies to UID/GID `10001`.
   Keeping the CA private keys preserves trust and certificate renewal. Never
   serve the entire storage volume over HTTP.
7. Start the four containers with the `up` command above. Existing schema 0003
   requires no initialization/migration. Keep native services stopped so exactly
   one worker owns the installation. For a future schema upgrade, follow the
   explicit offline migration process in [deployment](deployment.md).
8. Verify the old CA still validates TLS, readiness and worker/model health,
   redirects, session/role/CSRF checks, pin/reload/PDF/collection printing, database
   integrity and unchanged business/account/secret/media hashes. Retain the
   snapshot and original native directories until a later deliberate cleanup.

For this cutover, private snapshots and saved native unit definitions are under
`.local/container-tailnet/2026-10-04/`. The installation-specific `migrate.py`
and `seed.py` helpers alongside that directory retain the exact operations and
verification. They refuse existing destinations; they are not routine startup
commands. Assign modes before changing ownership when using a helper with
dropped capabilities. The snapshot contains credentials and must stay private.

## Rollback and updates

Before accepting new writes, a failed cutover can be rolled back by stopping the
container project, then recreating the saved native units with the original
config/data and CA paths. Reuse [native Tailscale bindings](native-tailnet.md).
Never start both workers against the same data directory.

After containers have accepted writes, the native data copy is stale. Stop all
container writers, snapshot/export the complete current app data volume and
verify it before transferring it back to a separate native data tree. Preserve
current account secrets and CA state. Do not simply restart the old native copy
and discard intervening changes. A schema-changing rollback also requires a
compatible application version; there are no automatic down-migrations.

For updates, back up current data/secrets/CA, retain prior images and env files,
build explicit new image tags, stop writers, apply any required offline migration,
then recreate with `up -d --no-build --pull never --wait`. Restart alone does not
select a newly built image. Do not overwrite model artifacts while they are used.
