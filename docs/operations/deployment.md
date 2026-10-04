# Container quick start

This guide creates a new Boxen installation with Docker Compose. It includes the app, a background worker and local HTTPS. Data and certificates persist in named volumes. AI is optional and disabled in the base setup.

Already running Boxen? Use [Backups and upgrades](#backups-and-upgrades). Moving a native installation requires an explicit [migration](container-tailnet.md); starting Docker does not copy its inventory.

## 1. Check prerequisites

- Git, Bash, Docker and the **Docker Compose v2** plugin (`docker compose`, with a space).
- A local disk for Docker volumes. Production keeps at least **2 GiB and 5% free**, in addition to images, inventory and backups.
- Internet access for the initial source checkout and image build. The core installation can run offline afterward.

Linux x86-64 is the tested platform. Docker Desktop, ARM64 and GPU inference are not currently qualified. Python, Node, `uv` and pnpm are installed inside the image build; they are not host prerequisites.

```sh
git --version
docker version
docker compose version
```

Docker must be running and accessible to your account. Install it using the [official Docker instructions](https://docs.docker.com/engine/install/) if needed.

## 2. Get Boxen and choose an address

```sh
git clone https://github.com/trie-me/boxen.git
cd boxen
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env` before starting. It is ignored by Git. These are the four settings most installations need:

| Setting | Default | What it controls |
| --- | --- | --- |
| `BOXEN_HOST` | `localhost` | Name or IP people use in their browser. No scheme, path or port. |
| `BOXEN_BIND_ADDRESS` | `127.0.0.1` | IP on the Docker host that accepts connections. |
| `BOXEN_HTTPS_PORT` | `8443` | Published HTTPS port; the browser URL includes it. |
| `BOXEN_ANONYMOUS_ACCESS` | `editor` | `editor` allows inventory changes, `viewer` allows reading, `off` requires sign-in. |

Use the defaults for this computer only. For a phone or another computer on your LAN, replace the example IP below with the Docker host's actual stable LAN IP:

```dotenv
BOXEN_HOST=192.0.2.10
BOXEN_BIND_ADDRESS=192.0.2.10
BOXEN_HTTPS_PORT=8443
BOXEN_ANONYMOUS_ACCESS=off
```

For a host already connected to Tailscale, the base stack can bind directly to its Tailscale IPv4 address:

```dotenv
BOXEN_HOST=boxen.example-tailnet.ts.net
BOXEN_BIND_ADDRESS=100.64.0.10
BOXEN_HTTPS_PORT=8443
BOXEN_ANONYMOUS_ACCESS=off
```

Replace both placeholders with your machine's values. Tailscale runs on the host, not inside this stack. Other devices need access to that tailnet and working name resolution. For IPv6 plus redirects from a previous LAN address, use the [extended Tailscale profile](container-tailnet.md).

`BOXEN_HOST` is the browser address; `BOXEN_BIND_ADDRESS` must be an address the host actually owns. A DNS name must resolve to that address on each client. `0.0.0.0` as the bind address exposes the port on every IPv4 interface; prefer a specific trusted interface. Allow the chosen port through the host firewall from your intended network. Do not forward it from the public internet.

Anonymous permissions apply to everyone who can reach the server. An owner account is still required for administration and backups. You can change anonymous access later and recreate the services with `up -d`.

## 3. Build, initialize and start

The repository includes Compose files and a small helper, `scripts/boxen-compose`. It selects `deploy/.env`, the base Compose file and the source-build overlay. It forwards all arguments to Docker Compose and can be called from any directory. The examples below run from the repository root.

Run each command only after the previous one succeeds:

```sh
./scripts/boxen-compose config --quiet
./scripts/boxen-compose build web caddy
./scripts/boxen-compose run --rm --no-deps --pull never init
./scripts/boxen-compose up -d --no-build --pull never --wait web worker caddy
./scripts/boxen-compose ps
```

**Save the one-time setup token printed by `init` privately.** The init container does not retain Docker logs. It creates the database and installation keys; web startup does not initialize or migrate automatically.

The first build downloads dependencies and may take several minutes. The default tags (`boxen:0.1.0`, `boxen-caddy:0.1.0`) name images built on your machine. **There are no published Boxen images to pull yet.** If you have transferred compatible images with `docker image load`, skip the build. See the [image settings](container-storage.md#compose-settings) for custom tags.

Open **`https://localhost:8443`** for the default configuration, or **`https://YOUR-HOST:YOUR-PORT`** for your chosen address. Use HTTPS. Localhost on a phone refers to the phone, not the server.

Only Caddy's HTTPS port is published. The API, worker and optional local AI communicate on a private Docker network. The web, worker and proxy run as UID/GID `10001:10001` with read-only container filesystems and writable persistent volumes.

## Local HTTPS and camera

Caddy issues a certificate from a CA created for this installation. A browser warning is expected until your device trusts that CA. A Tailscale hostname still uses this local CA; this setup does not request a public certificate.

Export the **public certificate** on the Docker host:

```sh
mkdir -p .local/boxen-trust
./scripts/boxen-compose cp caddy:/data/caddy/pki/authorities/local/root.crt .local/boxen-trust/root.crt
openssl x509 -in .local/boxen-trust/root.crt -noout -subject -fingerprint -sha256
curl --fail --cacert .local/boxen-trust/root.crt https://localhost:8443/api/v1/health/ready
```

Use your configured host and port in the last command. `openssl` and `curl` are optional host tools for checking the exported certificate and HTTPS connection.

Transfer `root.crt` to each client through a trusted channel, compare its SHA-256 fingerprint with the host's output, and import it as a trusted certificate authority using that device/browser's certificate settings. Some browsers use their own trust store. On iOS, installing the certificate profile also requires enabling full trust under **Settings → General → About → Certificate Trust Settings**. Restart the browser if the warning remains. See [Caddy's local HTTPS explanation](https://caddyserver.com/docs/automatic-https#local-https) and [Apple's certificate-trust instructions](https://support.apple.com/en-us/102390).

Trust only the public `root.crt`; never distribute `root.key` or the whole Caddy volume. Preserve the CA volumes so upgrades do not require trusting a new CA. Opening the app through a different hostname or IP can produce a certificate or origin error—use the configured address consistently.

Live browser camera scanning requires trusted HTTPS and camera permission. Photo/QR uploads are also available. Actual camera behavior depends on the device/browser; a successful HTTPS check does not test a physical phone or printer.

## 4. Create your administrator

1. Open `/setup` at your Boxen address.
2. Enter the one-time token from `init`.
3. Choose a username (the form suggests `admin`) and a unique password of at least 12 characters.

There is no factory password. The first account is the protected core system administrator. Setup closes after that account is created. Creating it does not change the anonymous-access setting.

If you missed the token, retrieve it privately on the host before setup is complete:

```sh
./scripts/boxen-compose exec web cat /var/lib/boxen/data/secrets/setup-token
```

Do not post the result in an issue or chat. The token file disappears after successful setup. Running `init` again will not reset an existing account; use [account recovery](../help/administration.md) if needed.

## 5. Try the installation

Create a box, add an item and upload a photo. Search for the item to find the box again. Pin two boxes with **Pin label for printing**, open **Print list**, and download a sheet. A collection's **Print collection labels** action prints all its boxes directly.

Batch labels use Letter paper with ten 4 × 2-inch labels (Avery 5163/8163 layout). Use actual size / 100%, portrait and single-sided printing; check alignment on plain paper first. A starting-position control supports partly used sheets.

Open **System** to check the worker. AI being unavailable is expected in the base stack. Open **Help and setup** for the bundled user and operations guides.

## Daily commands

```sh
./scripts/boxen-compose ps
./scripts/boxen-compose logs --tail 100 web worker caddy
./scripts/boxen-compose stop
./scripts/boxen-compose up -d --no-build --pull never --wait web worker caddy
```

`stop` pauses the installation. `down` removes containers and the project networks but keeps named volumes. **Do not use `down --volumes` to stop or upgrade**: it deletes inventory and certificate volumes. Containers restart automatically after Docker/host restarts unless you stopped them explicitly.

Changing `.env` needs `up -d` to recreate affected containers; `restart` alone does not apply changed environment values. Keep the same project name and selected overlays for every command. A different project name selects different named volumes and appears to be an empty installation.

The default project name is `boxen`. To manage a separate instance:

```sh
BOXEN_ENV_FILE=/absolute/path/second.env ./scripts/boxen-compose -p boxen-second config --quiet
```

Use a different port or bind address, and repeat the same environment-file and `-p` selection on all its commands. `BOXEN_ENV_FILE` is a helper option; the [configuration reference](container-storage.md) explains precedence and advanced overrides.

## Backups and upgrades

After creating the administrator, use **System → Backups** to create and verify an inventory backup. Copy backups to separate storage. The worker also schedules daily backups; **automatic pruning is not implemented**, so monitor disk usage.

An inventory backup includes the database and original photos. Installation secrets, model files and Caddy CA state are excluded. Preserve a protected copy of the installation's password pepper separately; losing it breaks existing password verification. Follow the [recovery runbook](recovery.md) for full-volume recovery or moving hosts.

For a source update, retain the previous image tags/configuration and a verified backup. Use new image tags in `.env` if you want to keep previous images easily addressable. Run from your clean checkout:

```sh
git pull --ff-only
./scripts/boxen-compose build web caddy
./scripts/boxen-compose stop
./scripts/boxen-compose run --rm --no-deps --pull never init
./scripts/boxen-compose up -d --no-build --pull never --wait web worker caddy
./scripts/boxen-compose run --rm --no-deps --pull never web verify
```

`init` applies required schema changes explicitly while web and worker are stopped; it preserves existing inventory and setup state. Read the integrity report as well as the exit status of `verify`. If a command fails, stop the sequence and diagnose it. Do not restart an older app against a migrated database unless its compatibility is established; use the matching backup for rollback. If using AI or OIDC, include the same overlays on these commands and build the AI image too when its code changes.

## Separate local model container

Skip this section to run without AI. Local vision needs a provisioned model profile and enough RAM/CPU. The provided Qwen3-VL 2B CPU profile has about 1.55 GB of model/projector files, plus its runtime. Model weights are not in the Docker image and are never downloaded at runtime.

Follow [model provisioning](models.md#reproduce-provisioning) to prepare and hash-check a profile. That preparation currently uses the native Python environment described in [development setup](development.md); the base Boxen installation does not need it. With a complete existing profile, only Docker is needed for import. Set in `deploy/.env`:

```dotenv
BOXEN_AI_PROFILE=qwen3-vl-2b-q4-cpu
BOXEN_AI_THREADS=8
BOXEN_AI_CPUS=8
BOXEN_AI_MEMORY=8g
```

Use a shell function to keep the selected overlays consistent. Define it in each new terminal, from the repository root:

```sh
boxen_local_ai() {
  ./scripts/boxen-compose -f deploy/compose.ai-local.yaml -f deploy/compose.ai-build.yaml "$@"
}
boxen_local_ai config --quiet
boxen_local_ai build boxen-ai
boxen_local_ai run --rm --no-deps --pull never \
  --volume /absolute/provisioned/qwen3-vl-2b-q4-cpu:/source:ro model-import
boxen_local_ai up -d --no-build --pull never --wait web worker caddy boxen-ai
```

Replace the source path with your actual profile directory. The import tool verifies hashes, copies into this project's model volume and refuses overwrites. It alone runs with the ownership privileges needed to prepare files; runtime containers read the model volume without root access. AI receives no inventory volume and exposes no host port.

Use `boxen_local_ai` for later management commands, and include `boxen-ai` when starting the stack. Loading may take time. Check **System**, then upload a photo, request analysis and review the suggestions before accepting them. These resource defaults are configurable limits, not a performance guarantee.

## Optional remote vision server

Use remote AI **instead of** the local overlay. It needs a server implementing [Boxen's vision contract](remote-ai.md), not just an arbitrary OpenAI-compatible URL. Requested analyses send resized photos to that endpoint. There is no automatic cloud fallback.

Set `BOXEN_AI_PROFILE`, `BOXEN_AI_BASE_URL` and `BOXEN_AI_PROFILES_DIR` in `.env`. The profiles directory must contain `<profile>/manifest.json`, readable by container UID 10001; remote mode does not need weights. Start with:

```sh
boxen_remote_ai() {
  ./scripts/boxen-compose -f deploy/compose.ai-remote.yaml "$@"
}
boxen_remote_ai config --quiet
boxen_remote_ai up -d --no-build --pull never --wait web worker caddy
```

Add `-f deploy/compose.ai-remote-auth.yaml` inside that function for a bearer-token file selected by `BOXEN_AI_API_KEY_SOURCE`. Add `-f deploy/compose.ai-remote-ca.yaml` for a custom public CA file selected by `BOXEN_AI_CA_SOURCE`. These are host file paths; do not put secret values in `.env`. Use HTTPS; explicitly allowing insecure HTTP sends photos, prompts and any bearer token unencrypted. Stop the old `boxen-ai` service and drain/cancel pending analysis before switching modes.

## Optional OIDC sign-in

Local accounts need no identity provider. For OIDC, register a provider client, prepare private provider JSON/client-secret files, and set `BOXEN_OAUTH_CONFIG_DIR` to their absolute host directory. Follow the complete [authentication setup](../help/authentication.md#configure-an-oidc-provider) for the JSON format, callback URL, permissions and explicit user bindings.

```sh
./scripts/boxen-compose -f deploy/compose.oauth.yaml config --quiet
./scripts/boxen-compose -f deploy/compose.oauth.yaml up -d --no-build --pull never --wait web worker caddy
```

Include the OAuth overlay on later commands, together with your AI overlay if applicable. It gives the web service outbound provider access. Users must already have an account and an issuer/subject link; OIDC does not grant access automatically based on an email address. The core administrator remains a local account.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Configuration file missing | Copy `deploy/.env.example` to `deploy/.env`, or point `BOXEN_ENV_FILE` at your file. |
| Image pull denied / image missing | The default tags are local builds. Run `build web caddy` before `init`; keep the same `.env` and image tags. |
| Cannot assign requested address | `BOXEN_BIND_ADDRESS` must belong to this host. Ensure the Tailscale interface is up before starting a tailnet bind. |
| Port already allocated | Select a free `BOXEN_HTTPS_PORT` and use it in the browser URL. |
| Web unhealthy / schema not ready | Read `logs --tail 100 web`; run `init` on this project's existing volume with services stopped. |
| Permission denied on mounted files | Normal containers use UID/GID 10001. Follow the [storage and permissions guidance](container-storage.md#volumes); avoid changing unrelated host directories. |
| Low-disk error | Free space for the production reserve (2 GiB and 5%) plus uploads/backups. Review old backups manually. |
| HTTPS check or browser certificate fails | Use the configured host, export this project's CA, and trust it on the client. A new project/CA needs new trust. |
| Phone cannot connect | Use the server's address, not `localhost`; check firewall, DNS, tailnet access or guest-Wi-Fi isolation. |
| Login/edit rejected with an origin error | Use the exact configured HTTPS host and port. After changing `.env`, recreate with `up -d`. |
| Inventory appears empty | Check the project name and volume selection before running setup. Docker does not import a native data directory. |
| AI unavailable | Expected without an AI overlay/profile. With local AI, inspect `logs --tail 100 boxen-ai` and verify the imported profile. |

For all supported settings and mounts, see the [configuration reference](container-storage.md).
