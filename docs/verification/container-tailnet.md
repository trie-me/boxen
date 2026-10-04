# Tailscale container deployment evidence

Deployed 2026-10-04 on Linux amd64, Docker Engine 29.7.2 and Compose 5.5.0.
Current URL: **https://boxen.example-tailnet.ts.net:8443**.
See [the operations runbook](../operations/container-tailnet.md).

## Shipped configuration

- `compose.tailnet.yaml` adds Tailscale IPv6 and HTTP bindings plus legacy LAN
  redirects to the existing IPv4 HTTPS binding. The merged configuration has
  exactly six specific proxy sockets; no web, worker or inference ports publish.
- `Caddyfile.tailnet` retains local CA issuance, private CA storage and isolated
  public certificate routes. `default_sni` selects the legacy IP certificate for
  IP-address clients, which omit SNI; Docker's bridge address cannot select that
  certificate implicitly. See [Caddy's default SNI option](https://caddyserver.com/docs/caddyfile/options#default_sni).
- The wrapper `scripts/boxen-tailnet` consistently selects project `boxen-tailnet`,
  `.local/boxen-container.env`, local AI and source build overlays.
- Built-in Help includes “Tailscale containers” at `/help/container-tailnet` and
  the previous native setup for rollback reference. Deployment help links to it.
- Proxy configuration is bundled in its image and included in the existing
  build-context allowlist. No inventory or credentials enter build context.

## Verification

All 53 container packaging/profile-import tests pass. Ruff, shell syntax,
TypeScript/build, Compose configuration and final whitespace checks pass.
Three images built locally:

| Image | Image ID prefix |
| --- | --- |
| `boxen:tailnet-20261004` | `506888ded076` |
| `boxen-caddy:tailnet-20261004` | `609743d7d322` |
| `boxen-ai:tailnet-20261004` | `07eeb4ba98028` |

The disposable smoke used ports 18743/18080 and a random project with its own
volumes. It verified strict TLS on both Tailscale IP families, legacy HTTPS and
HTTP redirects, rejected legacy writes, blocked private-key routes, anonymous
CRUD/media/search, individual and batch PDFs, worker readiness, data/session/CA
persistence across recreation, and actual local model analysis of the public
coffee fixture. Three suggestions were generated, an explicit acceptance worked,
and manual inventory remained usable after AI stopped. Its own containers,
networks and volumes were removed; no personal images were analyzed.

Reproduce with unused ports and the actual host addresses:

```sh
.venv/bin/python scripts/compose_smoke.py \
  --image boxen:tailnet-20261004 \
  --proxy-image boxen-caddy:tailnet-20261004 \
  --model-image boxen-ai:tailnet-20261004 \
  --port 18743 --http-port 18080 \
  --tailnet-host boxen.example-tailnet.ts.net \
  --tailnet-ipv4 100.64.0.10 \
  --tailnet-ipv6 fd7a:115c:a1e0::1234 \
  --legacy-ipv4 192.0.2.10 \
  --model-profile .local/boxen/data/models/qwen3-vl-2b-q4-cpu \
  --fixture-image .local/ai-downloads/coffee.png
```

## Live cutover

No queued/running analysis, maintenance or backup jobs existed at cutover. Native
units/config/frontend were saved privately; native services were stopped. The
stopped database, photos, backups, all account/session secrets and complete CA
state were copied into dedicated volumes, with the model imported separately.
No schema migration or new initialization ran. An ownership-order error in the
initial copy was corrected before successful startup; original files remained
untouched and all copied hashes were checked again.

Every copied database table matched before startup. After startup, all 26 stable
tables still matched; sessions, idempotency, OIDC transactions and worker settings
were excluded from the post-start comparison because they are runtime state.
Secret, media and backup hashes match exactly. Password-pepper binding, schema,
SQLite integrity, foreign keys, search, original media and model hashes pass.

All four containers are running. Web and model health checks pass; application
status reports database, worker, AI and search ready. All four native services
are inactive. Strict original-CA TLS passes over IPv4 and IPv6. Public certificate
downloads are unchanged. Legacy redirects, write rejection, Secure/HttpOnly
session cookies, anonymous admin denial, CSRF and old-origin rejection pass.

Live browser checks at widths 375 and 1280 pass: pin two labels, retain them after
reload, download the combined PDF, and navigate collection printing. No page
errors or inventory mutations occurred. Authentication setup and help routes load.

Private evidence and rollback material: `.local/container-tailnet/2026-10-04/`;
disposable results: `.local/container-tailnet/rehearsal.log`. These are local
operator artifacts, not source or public downloads. Images were not published.
Physical phones/printers, host reboot, ARM and Docker Desktop were not exercised.
