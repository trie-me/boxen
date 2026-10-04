# Boxen implementation and verification

Date: 2026-10-04. Independent local application; no event/submission integration or hosted service.

## Latest follow-up: Tailscale containers (deployed 2026-10-04)

The existing installation now runs as four containers (web, worker, proxy and
local AI), retaining `https://boxen.example-tailnet.ts.net:8443`, the original CA,
schema 0003, inventory and account secrets. Native services are stopped. A private
stopped snapshot remains for rollback. All 26 stable database table hashes and
secret/media/backup file hashes match the snapshot; integrity, foreign keys,
search and model checks pass.

53 packaging/import tests pass. Disposable dual-stack TLS, old-IP redirects,
CRUD/media/search/PDF, real local inference, recreation persistence and manual
operation with AI stopped pass. Live TLS, role/CSRF checks and desktop/mobile
pin/reload/combined-PDF/collection navigation pass with no inventory mutations.
See [container Tailscale evidence](container-tailnet.md) and
[operation/restart/rollback instructions](../operations/container-tailnet.md).

## Previous: native Tailscale address (2026-10-04)

The native installation was first moved to
`https://boxen.example-tailnet.ts.net:8443`, using the same local CA. Web, worker
and proxy restarted; local AI stayed running. The proxy binds to the host's
Tailscale addresses and redirects old LAN bookmarks. Strict TLS readiness,
session/CSRF restrictions, live two-label pin/reload/PDF download and collection
printing navigation pass on desktop/mobile. The latest authentication frontend
and 12 existing business/account/audit/schema/identity table hashes are preserved;
database integrity and foreign keys pass. See the
[native Tailscale runbook](../operations/native-tailnet.md).

## Collection names on labels (deployed 2026-10-03)

All individual and batch PDF label formats now show current collection names
beneath the box name, with deterministic multi-membership ordering and bounded
overflow. QR/code size and stock geometry are preserved. All 94 label tests pass,
including 37 new membership/cache/overflow/QR cases; rendered compact, A4 and
Letter layouts were visually checked. See [collection-label verification](collection-labels.md).
This was deployed with the authentication release to the existing native
installation on 2026-10-03.

## Authentication store and administration (deployed 2026-10-03)

Implemented optional OIDC sign-in, exact provider subject bindings, a protected
local core administrator, salted and peppered Argon2id passwords, session
revocation/sign-in history, offline admin recovery and ten public local help
pages. Migration 0003 preserves old account/data history and old backups; existing
passwords upgrade on successful login. Provider registration/configuration remains
an operator step. See [authentication verification and deployment handoff](authentication-store.md).

771 backend tests pass (two opt-in model tests skipped), with all 72 API operations
exercised; 184 frontend unit tests and 14 browser scenarios pass. Types, lint,
formatting, OpenAPI, accessibility and final staged build pass. The updated Docker
image builds and its offline non-root smoke test verifies core setup and help.
The native installation was upgraded to schema 0003 on 2026-10-03 after a
rehearsal and private backup; live setup/help and permission checks passed.

## Previous: batch label printing (deployed 2026-10-03)

Boxes can be pinned into an ordered, browser-persisted print list, or a whole
collection can be printed directly. Letter PDFs lay out ten 4 × 2-inch labels
per page, with automatic pagination, partly used sheet support and ±3 mm
alignment adjustments. Collection printing includes archived members. The
existing individual-label profiles remain available.

682 backend tests pass (two opt-in real-model tests skipped), including all
61 API operations; 184 frontend units pass. Three new desktop/mobile printing
browser scenarios, nine existing LAN/organization scenarios and seven signed-in,
viewer and session-recovery scenarios pass (19 total).
PDF geometry/font/QR checks, both PDF pages and desktop/mobile visual review,
WCAG AA checks, types, formatting, lint, OpenAPI validation and staged build pass.
Deployed to native HTTPS on 2026-10-03 after backing up the database and old
frontend index. Only web was restarted; worker/proxy/AI, inventory and config
were preserved. Live two-box pin/reload/PDF-download and collection navigation
checks pass on desktop/mobile. See [batch printing evidence](batch-label-printing.md).

## Previous: container deployment and separate AI

Rev1 checkpoint `bb5285a` / `rev1-checkpoint` precedes the Docker changes. App,
HTTPS proxy and optional CPU inference images build; image-only Compose,
source-build overlays, persistent data/CA/model mounts and explicit remote AI
configuration are implemented. The UI discloses remote analysis and its
operator-reported model identity. No Docker Hub image was published.

653 backend tests, 180 frontend units and 8 browser scenarios pass. Disposable
HTTPS CRUD, persistence across recreation, network-disabled core/backup,
actual separate-container model inference and manual editing after AI shutdown
pass. Native services/data remain unchanged. See [container verification](containers.md)
and the [deployment guide](../operations/deployment.md).

## Previous: native LAN HTTPS

The existing native app now runs at `https://192.0.2.10:8443`, with the old
HTTP address redirecting and an isolated public certificate setup page at
`http://192.0.2.10:8000/trust/`. Verified strict TLS, anonymous writes in a
disposable fixture and camera start/stop with synthetic media; read-only live
checks pass. Inventory/account/schema tables were preserved exactly across a
verified offline backup and cutover. No host-wide trust or global install.
Motorola certificate installation and camera permission still require the user;
physical phone success is not claimed. See [TLS evidence](native-https.md) and
[phone setup](../operations/native-https.md).

## Analysis review status

Photo cards now show the actual remaining suggestion count, and stop prompting
for review once their chips are accepted or removed. Zero-detection photos,
mixed reviewed/pending photos, reanalysis and reviews completed in another
browser are covered. Unavailable status data is not treated as completed review.
174 frontend unit tests and16 relevant browser scenarios pass, along with
TypeScript, formatting and production build checks. No backend, database or
network changes are required. See [status evidence](analysis-review-status.md).
The tested frontend is deployed on the existing LAN app, with read-only live
mobile-width verification and no service restarts or inventory mutations.

## Contextual search suggestions

Search now offers local typeahead with explicit entity types and source boxes.
`BX-` plus two valid code characters suggests boxes; ordinary text of at least
two letters/numbers suggests confirmed items, tags and collections. Full Search
still includes box names and descriptions. Filters, archive visibility and
existing read permissions apply. Debounce, cancellation, bounded failures,
keyboard/manual selection, Unicode composition and touch selection are covered.

476 backend tests,164 frontend unit tests and39 browser scenarios pass;60/60
API operations retain successful coverage. Two opt-in real-AI cases are skipped
in this regression run. No schema, data, account or network changes are required.
The tested build is deployed on the native LAN app; read-only live checks
confirmed contextual suggestions and readiness after restarting only web.
See [typeahead evidence](contextual-search-suggestions.md) and
[ADR-0009](../system-design/adrs/0009-contextual-search-suggestions.md).

## Authentication feedback and mobile QR recovery

Setup, sign-in and re-authentication now display actionable inline field errors,
retain drafts and read actual autofilled values. A disposable first-owner test
creates an account through the real endpoint, logs out and signs back in; no
real account or credential was created, reset or read for these repairs.

QR photos now have bounded decoding, visible progress/errors, cancellation and
same-file retries. The phone UI offers `Take QR photo` with a native capture
hint, including on HTTP. Continuous live-camera access still requires trusted
HTTPS; no certificate trust or origin configuration was changed. The exact
physical Motorola failure is not claimed reproduced or device-qualified.

359 backend tests,132 frontend unit tests and31 browser scenarios pass; all59
API operations retain successful coverage. Two opt-in real-AI tests are skipped
in this regression run. The combined tested build is deployed on the existing
LAN app; only the web service restarted. Read-only live checks confirm the new
setup guidance and mobile scanner, readiness and no external browser requests.
See [authentication and scanner evidence](auth-and-mobile-scanner.md).

## Tags and collections

Box tags and named collections are implemented and deployed on the existing
native LAN app. Collections provide combined contents grouped by source box or
item name while preserving each item's identity, quantities and original box.
Box lists/search filter by tags and collections; search indexes their names.
Anonymous editing, archived membership and stale-write protection are covered.
326 backend tests,91 frontend unit tests and16 browser scenarios pass; all59 API
operations have successful coverage. A verified pre-upgrade backup preceded the
offline0002 migration; exact original source-row comparisons, integrity, foreign
keys and search verification pass. See [current evidence](tags-and-collections.md).

## Labels and chip-set review

The box-name label requirement is visually verified in all three PDF profiles
and the browser preview; 29 new label regression checks pass. AI review now uses
removable item chips, an add-item field and one atomic Accept items action.
Detected quantities/evidence remain available through optional chip details.
239 backend tests,64 frontend unit tests and14 browser scenarios pass. The
tested build is deployed on the native LAN app; only the web service restarted.
A reproducible QR-upload mask edge case was also fixed without changing camera
decoding or introducing remote resources. See [current evidence](labels-and-chip-review.md).

## Delivered software

- FastAPI/Python 3.13 backend, React/TypeScript cyberpunk web UI, local SQLite with forward-only Alembic migration and FTS5 search.
- Boxes, Markdown descriptions, exact decimal inventory quantities, lifecycle/restore, photographs/captions/reordering, safe local derivatives, and reviewed AI observations with provenance.
- Reusable tags and named collections, overlapping memberships, combined source-preserving itemization and tag/collection search filters.
- QR codes with typed-code checksum, browser-local uploaded/live-camera decoding, and deterministic vector PDF labels in 62 × 29 mm, 4 × 2 inch, and A4 14-label formats.
- Anonymous editing by default, with opt-in read-only or account-required access. Optional local owner/editor/viewer accounts; administration stays owner-only.
- Single local worker, bounded inference adapter, integrity-pinned local model provisioning, backups, recovery and repair commands, local TLS/container deployment.

## Scope correction

The owner's clarification supersedes the original capacity requirements: this is a single/low-user app, and capacity testing is not required. No capacity benchmark was completed or retained. See [ADR-0005](../system-design/adrs/0005-small-local-app-and-anonymous-access.md).

`BOXEN_ANONYMOUS_ACCESS=editor` is the default: ordinary box/inventory/photo/review editing needs no account setup or login. `viewer` is explicitly read-only; `off` requires sign-in. Neither anonymous mode grants system administration or irreversible purge. Native development supports explicit trusted-LAN HTTP binds and one exact browser origin; production retains HTTPS. These corrections are recorded in ADR-0005.

## Photo collection and token-limit repair

The user confirmed Mac browser connectivity resolved. The subsequent real-photo
token-limit failure is repaired and deployed with `inventory-v3`: compact output,
one bounded larger-budget retry, no partial suggestions, and recorded token usage.
The exact failed upload completed in10,591ms with8 pending suggestions in an
isolated regression; the public outside-a-box coffee photo took6,235ms. These
are operational timings, not completeness/accuracy or1–2second guarantees.

Photos now explicitly represent collective box contents regardless of where they
were taken. Analyze-all, durable per-photo state, explicit reanalysis and shared
review are implemented. Linking another view to an existing item leaves quantity
unchanged. This is independent per-photo inference, not joint multi-image identity
reasoning. See [ADR-0006](../system-design/adrs/0006-photo-collection-inventory.md)
and [current AI verification](ai-photo-collection.md).

Current checks: **166 backend tests passed**, 52/52 API operations covered,
**44 frontend unit tests**, **5 LAN browser scenarios** and **7 existing browser
scenarios** passed. The2 opt-in real-model cases were separately run and passed;
their ordinary-suite skips are not counted as passes. Typecheck, build, lint and
format checks passed. Tests use disposable inventory. The original live photo
was already marked deleted when a retry was attempted; its deletion was preserved
and no new live suggestions or confirmed items were created.

## Verification evidence

Original build run: **139 backend tests passed**, 87% measured Python statement coverage, plus **3 frontend unit tests and 7 browser scenarios**. These historical numbers are not proof of LAN HTTP or real AI behavior. See the current repair evidence below. CLI subprocess statements were not included in that coverage percentage. Tests use disposable data, not the owner's inventory.

- OpenAPI: every successful tested JSON response is validated against the contract; all 52 operations have successful coverage.
- Browser: seven Chromium scenarios pass, including anonymous opening/admin denial, session-expiry draft preservation, concurrent-edit conflict handling, camera-denial fallback and late-permission cleanup, photo upload, search, typed/uploaded QR lookup, and actual PDF preview/download.
- Layout/accessibility: no horizontal overflow at 320/375/768/1024/1440 CSS px on the home screen; ten main phone routes and box detail pass automated WCAG A/AA axe checks. This is not a substitute for manual assistive-technology testing.
- Printing: all three actual generated PDFs rasterize at simulated 203 dpi and decode correctly; all 14 A4 QR labels decode. Physical printer/stock testing is separate.
- Offline: the non-root, read-only production image runs with `--network none`; anonymous access, protected administration, catalog/inventory/search, photos, labels/code resolution, worker backups, and AI-disabled core health pass. Browser requests remain local.
- Deployment: disposable Compose startup and trusted local HTTPS pass after correcting tmpfs quoting, Caddy file capabilities/unprivileged port, and proxy-only ingress networking. The temporary Compose resources were removed. See [deployment evidence](deployment.md).
- Dependencies: Python and production JavaScript audits found no known vulnerabilities when checked; PDF.js was updated before the clean JavaScript audit. Lockfiles and base-image digests are recorded in the project.

## Not claimed

- Broad model accuracy is not qualified. A real local Qwen3-VL CPU model is installed and operationally tested; it can still miss/misidentify objects and counts. The compact v3 path leaves detailed attributes and boxes null. Suggestions require review. See [current AI evidence](ai-photo-collection.md); synthetic tests alone are not evidence of recognition.
- No physical phone-camera, printer, label-stock, screen-reader, or full Safari/Firefox/Edge/current-previous browser qualification was performed.
- No high-concurrency/capacity benchmark is required or claimed.
- No public deployment, remote service, telemetry, auto-updater, or external inference dependency was introduced.

## Repeat the checks

After dependency installation, `make check` runs lint, formatting and type checks; `make test` rebuilds the UI and runs backend, frontend and browser tests. Browser tests need Chromium (or `CHROME_BIN` pointing to an installed Chrome). PDF tests require Poppler's `pdftoppm`. `make audit` contacts advisory services during development only; it is not a runtime operation. The network-isolated production smoke procedure is in `scripts/container_smoke.py` and the deployment verification notes.

JUnit and coverage reports from the local verification run are in `artifacts/tests.xml` and `artifacts/coverage.json`. Browser screenshots/traces are under `frontend/test-results/` and are ignored generated artifacts.

## Current local preview

The original `.runtime` preview processes stopped; the earlier claim that their availability was resolved was premature. The user's subsequent native installation is `/path/to/boxen/.local/boxen/data`. Both directories are preserved; neither has been merged or overwritten. The repaired application is supervised as transient user services `boxen-web`, `boxen-worker` and `boxen-ai`. Web listens at `http://192.0.2.10:8000`; inference listens only at `127.0.0.1:8080`. All use `.local/boxen/app.toml`, the existing `.local/boxen/data` and the project-local Qwen CPU profile. Their lifetime is independent of a chat command session; they are not boot-enabled services. Recheck live service state instead of relying on this paragraph as an uptime claim. Owner setup is not required for ordinary inventory editing or AI review.

Inspect with `systemctl --user status boxen-web boxen-worker boxen-ai`. Stop with `systemctl --user stop boxen-web boxen-worker boxen-ai`; this preserves data/model files. Do not run a duplicate worker or web process while these services are active. The [model runbook](../operations/models.md) gives foreground commands for subsequent starts. Loading `BOXEN_CONFIG_FILE=/path/to/boxen/.local/boxen/app.toml` supplies this host's matching application/model settings.

## LAN and anonymous-use repair evidence

- Focused backend checks: 37 passed; combined backend regression after AI fixes: **159 passed**, with 52/52 successful API operations covered. The opt-in real-model test is skipped in ordinary regressions and was separately run successfully, not counted as a synthetic pass.
- Genuine insecure-context browser scenarios: 3 passed on `http://boxen.test:8174`, mapped inside Chromium to a disposable loopback server. Confirmed `isSecureContext=false`, unavailable `crypto.subtle`, `crypto.randomUUID` and `navigator.mediaDevices`, no owner setup and default anonymous editor.
- Those scenarios cover box creation/editing, items/search, photo upload, PDF rendering/download, copy-code manual fallback, typed/checksummed codes and local QR-image lookup. CSRF and administrator denial remain enforced; no external assets or page errors occurred.
- Frontend unit tests: 29 passed, including secure-random UUID fallback and local QR checksum equivalence; TypeScript and production build passed. The original seven viewer/login/resilience/camera/accessibility scenarios also passed with the rebuilt frontend, using the already-installed Chromium via `CHROME_BIN=/usr/lib64/chromium-browser/chromium-browser`.
- Actual host verification: network interface owns `192.0.2.10`; the app listens specifically on that address/port8000 (not loopback), health returns ready, and the browser renders Anonymous Can Edit plus New box/create form at the LAN URL. Ethernet's existing `FedoraWorkstation` firewall zone already permits TCP8000 (its configured range is1025–65535); no firewall/router settings were changed. A physical phone has not been tested by the agent.
- Live browser camera still needs trusted HTTPS, a browser platform requirement. LAN HTTP explicitly supports typed/photographed QR and inventory image uploads.
- Final actual-model check: **1 passed in18.08s**, actual CPU inference17,136ms, through the supervised loopback8080 runtime. An anonymous editor created/uploaded/analyzed/reviewed/accepted/searched in a disposable installation with zero owners and setup still incomplete. Model found cup/saucer/spoon plus an unwanted table; incorrect text/attributes and boxes remain review concerns. No user's inventory was seeded or modified. JUnit: `artifacts/tests-real-ai-anonymous.xml`; full backend: `artifacts/tests-lan-ai-repair.xml`.
- Final running-app check: anonymous role `editor`; database, worker, Qwen3-VL AI and search all report ready through the LAN API and rendered System page. All three user services are active with no restarts at the verification time.
