# Container deployment verification — 2026-09-21

Source checkpoint created **before** these changes: commit `bb5285a`, annotated
tag `rev1-checkpoint`. The checkpoint excludes runtime inventory, secrets,
certificates, models and generated frontend output. It includes source-only
camera feedback that was not yet deployed to the native app.

## Implemented

- Image-only Compose with configurable app/proxy/AI image references for future
  Docker Hub use; separate source-build overlays. No publication occurred.
- App image reused for web, one worker and explicit init/maintenance. Built UI,
  fonts and dependencies are embedded. No install/download happens at startup.
- Shared persistent application volume mounted at the parent of `data`, retaining
  SQLite WAL/locking and offline restore/quarantine semantics.
- Optional separate CPU model image, private network and read-only model volume;
  it does not receive inventory or session secrets. Explicit network-disabled
  model import tool verifies the copied profile and sets ownership.
- Remote vision opt-in: metadata-only profiles, HTTPS by default, optional
  token/custom-CA files, no redirects/proxy discovery/fallback, bounded responses
  and operator-reported provenance. Remote configuration is disclosed in the UI.
- Build-context allowlist excludes `.local`, databases, photos, weights,
  certificates, keys, dependency caches and generated output.

## Reproducible checks

Host: Linux amd64, Docker Engine 29.7.2, Compose 5.5.0. Built local tags:

| Image | Local image ID | Uncompressed size |
| --- | --- | --- |
| `boxen:container-dev` | `8516d112209eb5839abaa9b4fb450e29cf90f1ae17a8e3c6a4a3f3c4f47b2ea0` | 212,369,470 bytes |
| `boxen-caddy:container-dev` | `0cfe390feb8b0b54a941eb6ade64e3f952283d88eceb7eddd1d78802b49a87fa` | 102,996,563 bytes |
| `boxen-ai:container-dev` | `e6ab671710ecda890b19b636228ff1d9791e27594891c497822f3c180154508b` | 213,848,078 bytes |

These are local image IDs, not published registry manifest digests or compressed
download sizes. The installed vision adapter's SHA-256 was compared with the
final source and matched. The initial transmitted build context was about 3 MB,
not the live data/model directory.

| Check | Result |
| --- | --- |
| Final full backend suite | **653 passed, 2 skipped**; all 60 API operations exercised successfully |
| Frontend unit tests | **180 passed** |
| Core/browser regression including remote disclosure | **8 passed**, including phone-width accessibility/layout and synthetic camera lifecycle |
| TypeScript, Ruff lint/format, Python typing | Passed |
| Production frontend and app/proxy/AI image builds | Passed |
| Static container contracts | **50 passed** (part of backend total); image-only base, non-root runtime, networks, volumes, secrets, context exclusion and explicit importer |
| Profile import | **3 passed** (part of backend total): valid copy/permissions, no overwrite, hash corruption and path escape rejection |
| Compose parsing | Base/build/local/remote/auth/CA combinations, LAN origin/port agreement and required-setting failures checked |
| HTTPS Compose core smoke | Passed with certificate validation using the fixture's own public CA, no TLS bypass or host trust change |
| Network-disabled image smoke | Passed with `--network none`: packaged UI, setup, protected admin, CRUD, uploads, search, PDF labels, QR resolution and verified backup |
| Real local inference container | Passed: public coffee-cup fixture yielded **3 pending suggestions**, no automatic inventory confirmation; explicit cup acceptance created searchable AI-provenance inventory |
| AI outage isolation | Passed: model stopped; web readiness, photo access and new manual inventory remained functional |
| Persistence | Data, photos, search, session/CSRF and CA survived forced web/worker/proxy recreation |

The two backend skips are the older opt-in real-photo tests. They do not imply
model verification was skipped here: the new Compose smoke exercised real
inference through separate web, worker and model containers. Remote transport
tests used mocks; no real image was transmitted to a non-local server.

Run the new smoke after building the local test tags:

```sh
.venv/bin/python scripts/compose_smoke.py
.venv/bin/python scripts/compose_smoke.py --model-profile /absolute/provisioned/qwen3-vl-2b-q4-cpu --fixture-image /absolute/public-fixtures/coffee.png
```

The script uses a unique `boxen-smoke-*` project, loopback HTTPS on 18743 by
default, fresh named volumes and only preloaded images. It copies the source
profile read-only into its own model volume. It cleans up only its own test
containers/networks/volumes in a `finally` block. Do not adapt its teardown to an
existing project. No capacity/load testing was performed.

## Issues caught during verification

The first core smoke failed in its own header setup, not the application; the
fixture was corrected and rerun successfully. An attempted Compose `run -v`
override did not remove an inherited read-only model mount. Rather than weaken
normal model execution, the explicit offline `model-import` service was added
and the real import/inference test rerun successfully. Only that tool has the
narrow file-ownership capabilities required for provisioning.

## Scope and limitations

- The current native installation was not migrated, restarted or reconfigured.
  Final checks retained the original web/worker/AI/proxy PIDs and zero restarts.
- No Docker Hub repository, push, public deployment, host trust, firewall,
  global toolchain or user inventory change occurred.
- All fixture containers/volumes were removed; local test images remain.
- ARM64, GPU, Docker Desktop, physical phone camera behavior and actual remote
  provider compatibility are not qualified by these checks.
- Full stopped-volume host relocation and Compose offline restore are still
  separate rehearsals; backend recovery tests and container persistence/backup
  are not substitutes for them.
- No release vulnerability/SBOM/signing gate or multi-platform publication was
  performed. These belong before an eventual public image release.
- Existing Starlette/httpx deprecation warnings remain. They did not fail tests.

Runbooks: [deployment](../operations/deployment.md),
[storage/configuration](../operations/container-storage.md),
[remote contract](../operations/remote-ai.md).
