# Boxen

**Know what is in every box.** Boxen is a self-hosted inventory app for photographed contents, searchable items and printable QR labels. Your inventory lives in SQLite and local photo storage. Once installed, the core app works without internet access.

- **Find things:** search box names, contents, tags and collections.
- **Organize a move or a room:** group boxes into collections without duplicating inventory.
- **Print a sheet of labels:** pin boxes from cards, search results or box details, then open **Print list**. Or open a collection and choose **Print collection labels**.
- **Look up a box:** scan its QR label or enter its code.
- **Keep photo storage small:** new uploads become WebP images, up to 2,048 pixels on the longest edge, with smaller thumbnails for browsing.
- **Optional photo assistance:** run a local vision model, review its suggestions and accept the items you want. AI is optional; manual inventory always works.

## Run with Docker

You need **Git, Bash, Docker and Docker Compose v2**. Linux x86-64 is the tested platform. Python, Node and package managers run inside the build; you do not need them on the host. The image names below are built locally—there are no published Boxen images to pull yet.

```sh
git clone https://github.com/trie-me/boxen.git
cd boxen
cp deploy/.env.example deploy/.env

./scripts/boxen-compose config --quiet
./scripts/boxen-compose build web caddy
./scripts/boxen-compose run --rm --no-deps --pull never init
./scripts/boxen-compose up -d --no-build --pull never --wait web worker caddy
```

Run each command after the previous one succeeds. **Keep the one-time setup token printed by `init`.** Open **[https://localhost:8443](https://localhost:8443)** on the Docker host. Caddy creates a local certificate, so your browser will initially show a certificate warning. Follow the [HTTPS trust steps](docs/operations/deployment.md#local-https-and-camera) to install this installation's public CA certificate.

The default allows **anonymous editing** on this computer. To require sign-in, set `BOXEN_ANONYMOUS_ACCESS=off` in `deploy/.env` before starting. Visit `/setup`, enter the setup token and create your administrator with a unique password of at least 12 characters. There is no default password. An administrator is needed for backups, users and other system settings even if anonymous editing stays enabled.

**Using a phone or another computer?** Set `BOXEN_HOST` to your server's reachable name or IP and `BOXEN_BIND_ADDRESS` to its LAN or Tailscale IP before starting. `localhost` on a phone means the phone. The [container quick start](docs/operations/deployment.md) walks through networking, certificate trust, first login and troubleshooting.

## Print labels

Pin several boxes, open **Print list**, and download one PDF. Collections can print all their members directly, including archived boxes. Pins are saved per browser and account.

Batch sheets use **US Letter, 4 × 2-inch labels, 2 columns × 5 rows** (Avery 5163/8163 layout), with up to 500 labels per PDF. Select a starting position for a partly used sheet and adjust alignment if needed. Print **actual size / 100%, portrait, single-sided**. Check a plain-paper test against your label stock before using a sheet.

## Manage the installation

```sh
./scripts/boxen-compose ps
./scripts/boxen-compose logs --tail 100 web worker caddy
./scripts/boxen-compose stop
./scripts/boxen-compose up -d --no-build --pull never --wait web worker caddy
```

Inventory and certificates persist in named Docker volumes. Ordinary `stop` or `down` keeps them; **`down --volumes` deletes them**. Use the [backup and upgrade instructions](docs/operations/deployment.md#backups-and-upgrades) before updating an existing installation.

## Documentation

| I want to… | Guide |
| --- | --- |
| Install Boxen, connect devices and fix startup problems | [Container quick start](docs/operations/deployment.md) |
| Understand every setting, volume and optional Compose file | [Configuration reference](docs/operations/container-storage.md) |
| Set up local users or OIDC sign-in | [Authentication](docs/help/authentication.md) |
| Learn boxes, photos, tags, collections and printing | [Using Boxen](docs/help/inventory.md) |
| Add local or remote vision AI | [Local AI setup](docs/operations/deployment.md#separate-local-model-container) · [Remote AI contract](docs/operations/remote-ai.md) |
| Use Tailscale with IPv6 and redirects from an old address | [Tailscale deployment](docs/operations/container-tailnet.md) |
| Back up, restore or move an installation | [Recovery](docs/operations/recovery.md) |
| Develop without Docker | [Native development](docs/operations/development.md) |
| Explore architecture and tested behavior | [System design](SYSTEM_DESIGN.md) · [Implementation status](docs/verification/IMPLEMENTATION_STATUS.md) |

The installation and user guides are also available in **Help and setup** inside Boxen, including before sign-in. Configuration examples use placeholder addresses; replace them with your own. Keep private configuration, inventory, keys and model weights out of Git.
