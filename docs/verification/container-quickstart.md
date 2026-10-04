# Container quick-start verification

Verified on 2026-10-04 with Linux x86-64, Docker Compose 5.5.0 and locally built app/proxy images. The public entry points are the [README](../../README.md), [container quick start](../operations/deployment.md) and [configuration reference](../operations/container-storage.md).

## Installation and persistence

Built the app and proxy through `scripts/boxen-compose build web caddy`. The smoke script now uses that same helper and the example environment file, with unique project names, unused loopback ports and temporary named volumes. It never targets an existing installation.

Both hostname and direct-IP installations passed:

```sh
.venv/bin/python scripts/compose_smoke.py \
  --image boxen:quickstart-20261004 --proxy-image boxen-caddy:quickstart-20261004 \
  --port 18743
.venv/bin/python scripts/compose_smoke.py \
  --image boxen:quickstart-20261004 --proxy-image boxen-caddy:quickstart-20261004 \
  --host 127.0.0.1 --port 18744
```

The image tags above identify local verification builds, not downloadable releases. Rebuild with your own tags and use free ports when reproducing.

Each run checked initialization, trusted HTTPS using its exported public CA, anonymous box/item creation, photo upload and retrieval, search, single and batch label PDFs, worker readiness, and expected AI-unavailable behavior. After container recreation, inventory, photos, sessions and the CA remained usable. First-owner setup succeeded; switching anonymous access off and recreating services rejected anonymous sessions and allowed the new administrator to sign in and read the existing inventory. Both runs removed only their own test volumes afterward.

The direct-IP run failed against the previous proxy configuration at HTTPS readiness. IP clients omit TLS SNI, so the base Caddyfile now sets `default_sni` to the configured host. The same check then passed with certificate verification enabled. Hostname access continued to pass.

## Documentation and packaging

- All 24 backend settings, the special TOML selector and all 20 Compose interpolation variables appear in the reference; helper/project-name options are included separately.
- Relative links and section anchors in the README and three operations guides resolve.
- Six Compose combinations validated: base, local AI, remote AI with token/CA mounts, OIDC, local AI plus OIDC, and extended Tailscale.
- The helper worked outside the checkout with a relative environment-file path; the documented advanced override retained base values and applied to init/web/worker. Missing configuration produced setup guidance.
- 53 packaging/profile-import tests passed. Python lint/format, shell syntax, frontend type checking and production build passed. The frontend build reports an existing bundle-size warning.
- The three new/revised Help guides rendered in Chromium at 1280- and 390-pixel widths without page overflow, missing in-page anchors or JavaScript errors; screenshots were visually reviewed.

Optional AI and OIDC overlays were checked for configuration merging here, not end-to-end provider/model operation. Their existing verification records cover separate exercises. This work does not qualify Docker Desktop, ARM64, GPU inference, physical phone camera behavior or printer alignment, and does not publish container images to a registry.
