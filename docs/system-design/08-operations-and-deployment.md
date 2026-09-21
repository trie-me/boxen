# Operations and Deployment Specification

## 1. Deployment profiles

### `core`

Runs proxy, web, worker, SQLite/media, but no AI runtime/model. All catalog, image, manual inventory, search, labels, scanning, users, backup, and maintenance features work. Analyze controls show `Local AI is not installed` with owner setup guidance.

### `ai-cpu`

Adds the pinned CPU inference runtime and a qualified Lite or Balanced model profile. Default worker slots: one.

### `ai-accelerated`

Adds a release-qualified accelerator-specific runtime and profile. It is a separate deployment artifact because host driver/device requirements differ. Falling back to CPU requires an explicitly installed CPU profile; it is never silent.

## 2. Service topology

```yaml
services:
  proxy:   # only LAN-published service: 80/443
  web:     # private :8000, read/write DB, read media
  worker:  # private, read/write DB/media/backups, call AI
  ai:      # optional private :8080, read-only models
```

The release repository MUST provide Compose configuration and equivalent systemd/native guidance. Compose health/dependency ordering is convenience only; every process independently retries bounded startup dependencies and exposes accurate readiness.

### Service users and mounts

| Service | Writable mounts | Read-only mounts |
| --- | --- | --- |
| Proxy | TLS state | Static proxy config |
| Web | DB directory, upload staging | Media originals/derivatives, frontend assets, secret file |
| Worker | DB, media, backups, temporary work | Models, application config/secret as required |
| AI | Runtime scratch only | Model profile files and per-request media view |

The web needs media write only if upload finalization is performed there; the preferred implementation stages upload in web and delegates derivative/finalization to a constrained local media service in the worker code. Whichever implementation is selected, mount permissions MUST match actual responsibility and be covered by deployment tests.

## 3. Release bundle

Every release bundle contains:

- pinned web/worker/proxy container images or offline OCI archives;
- frontend assets embedded in web image;
- Compose/systemd manifests and checksums;
- database migrations;
- built-in label profiles and embedded local font license files;
- API/AI schema contracts;
- SBOM and third-party notices;
- install/update/backup/restore/troubleshooting docs;
- optional separately licensed model profile bundle(s), each with manifest/checksums/license;
- release manifest signed or distributed with an independently verifiable checksum.

Runtime containers contain no package manager invocation or downloader. Loading a release from removable media is a supported path.

## 4. Installation preflight

The installer verifies before mutation:

1. supported OS/architecture and container/runtime capabilities;
2. local filesystem type and locking suitability;
3. available disk and inode reserve;
4. required ports or configured alternates;
5. hostname resolution plan;
6. CPU instructions and optional accelerator visibility;
7. ownership/permissions for data roots;
8. release/model checksums and licenses;
9. no existing incompatible schema/data root.

Preflight outputs a human-readable report and exits without partial installation on failure.

## 5. First-run sequence

1. Start proxy/web in setup-only mode; worker may start with no AI profile.
2. Generate installation ID and session secret using OS CSPRNG.
3. Initialize SQLite through migrations and verify schema checksum.
4. Enter the one-time host-console setup token and create the first owner through `/setup`; setup route permanently closes once a user exists and the token is destroyed.
5. Select/verify data, backup, and optional model profiles.
6. Configure exact origin and local hostname.
7. Generate local CA/leaf certificate and display root fingerprint/trust instructions.
8. Verify one phone/desktop connection.
9. Run database/media/search baseline integrity checks.
10. Write first-run completion audit entry and switch to normal mode.

First-run state is resumable. It never stores the owner password outside the final Argon2id hash.

## 6. Local naming and TLS

### Recommended origin

`https://boxen.local` advertised through mDNS on the local network. A user-configured local DNS name under `home.arpa` is preferred when the network provides reliable local DNS. An IP-address certificate is a documented fallback but is less stable.

### Certificate flow

- Caddy uses an internal CA persisted in the protected TLS volume.
- Setup displays the CA root SHA-256 fingerprint and provides an authenticated owner-only download.
- Owner installs the root on each phone/browser trust store and verifies fingerprint out of band.
- Leaf certificate covers the configured host/IP and is renewed locally; no ACME/internet access occurs.
- Caddy administration endpoint remains loopback/private and unauthenticated LAN access is impossible.
- Losing CA state requires explicit CA rotation and device re-enrollment, not transparent regeneration.

Live camera uses `getUserMedia`, which requires a secure browser context; therefore HTTP LAN access is not a supported application mode. QR-image upload and typed code remain functional alternatives to live camera, but still require access to the authenticated Boxen origin.

## 7. Startup and shutdown

### Startup order

1. Proxy starts independently and reports upstream unavailable until web is ready.
2. Web validates config/secrets/paths, opens DB, checks schema, applies authorized migrations, verifies FTS availability, then becomes ready.
3. Worker validates same schema, claims expired leases safely, verifies media/model profile, emits heartbeat.
4. AI loads and warms configured model before reporting ready; worker may be ready in degraded non-AI mode.

### Shutdown

- Proxy stops accepting new requests.
- Web receives a grace period to finish short transactions/uploads, then cancels incomplete staging work safely.
- Worker stops claiming, marks cancellation/renews lease as appropriate, allows bounded completion, then releases/lets lease expire.
- SQLite connections close through APIs and checkpoint policy; scripts never remove WAL files.
- AI unloads last.

Host reboot during any step must yield a recoverable state through staging/job/database invariants.

## 8. Health model

| Check | Liveness | Readiness | Authorized system view |
| --- | --- | --- | --- |
| Process event loop | Yes | Yes | Yes |
| Config/secrets valid | No detail | Yes | Yes |
| Database open/schema compatible | No | Yes | Yes |
| Disk reserve | No | Degrades writes | Yes |
| Worker heartbeat | No | Web remains ready | Yes |
| AI profile/runtime | No | Core remains ready | Yes |
| Search projection | No | Search-only degraded | Yes |
| Backup age/verification | No | No | Yes |
| Media integrity | No | No | Yes |

Unauthenticated liveness/readiness returns only `alive`, `ready`, or one generic problem. Detailed paths, versions, storage, model, and failures require an authenticated user and owner role where sensitive.

## 9. Logs and local observability

### Structured log fields

```text
timestamp, level, service, event, request_id, operation_id,
actor_id (when necessary), target_type, target_public_id,
duration_ms, result, safe_error_code
```

- JSON lines to stdout/container logs and optional rotating local files.
- Default retention: 14 days or 500 MiB, whichever comes first.
- No passwords, session/CSRF values, secret/config values, image/Markdown/item content, raw model prompts/output, absolute media paths, or CA private data.
- Stack traces are local error logs only and are omitted from user/API detail.
- Request query logging redacts search text by default; logs route template and result count only.

### Operational metrics

Metrics are stored/displayed locally: request counts/latency by route template/status, DB busy time, upload failures, disk usage/reserve, queue depth/oldest age, worker heartbeat, inference outcome/duration/memory, search verify state, backup age/result. They are not exported automatically.

## 10. Backup operation

### Schedule

- Default: daily at 02:00 host local time, configurable by owner.
- If host was off, run once after startup when the last verified backup exceeds 24 hours.
- Only one backup/verification job at a time.
- Keep 14 verified generations by default; failed/incomplete attempts do not count.

### Preconditions

- sufficient free space for estimated snapshot/media delta plus reserve;
- database quick check and no active migration;
- backup destination local and writable;
- no restore or destructive maintenance running.

### Success evidence

- manifest/checksum list written atomically;
- SQLite snapshot integrity passes;
- every referenced original exists and matches snapshot manifest policy;
- backup status `verified` with timestamp;
- owner-visible latest successful age and next scheduled time.

Backup failure never deletes the last verified generation.

## 11. Restore runbook

Restore is deliberately outside the running web API:

```text
boxen restore preflight <backup-path>
boxen restore apply <backup-path> --confirm-installation <id>
boxen restore verify
```

Runbook:

1. Stop web/worker/AI; keep proxy maintenance page or stop all listeners.
2. Preflight checks manifest, checksums, format/schema compatibility, disk, ownership, and target installation intent.
3. Move current data root to timestamped quarantine without deleting it.
4. Restore into a new sibling root; verify DB integrity, foreign keys, media references/checksums.
5. Atomically activate restored root.
6. Start prior-compatible application version, then run approved migrations.
7. Rebuild derivatives/search if omitted or version-mismatched.
8. Run smoke/integrity checks and sign in locally.
9. Keep quarantine until owner confirms, then remove through a separate explicit command.

The tool prints no sensitive record content.

## 12. Upgrade runbook

1. Read release notes, schema/model/profile compatibility, and minimum resources.
2. Verify release manifest, images, SBOM, model bundle.
3. Run upgrade preflight and create/verify pre-upgrade backup.
4. Stop new mutations; finish/cancel worker jobs safely.
5. Load new images/artifacts locally.
6. Run migrations under exclusive application migration lock.
7. Start web, run readiness and migration smoke tests; then worker/AI.
8. Run API/UI smoke, FTS verify, one label fixture, one scanner decode fixture, and model readiness.
9. Retain prior images and backup until acceptance window passes.

If migration/start fails, restore the verified pre-upgrade backup and prior release. Database down-migrations are not used.

## 13. Maintenance jobs

Operations worker supports durable single-flight jobs:

- `search_verify`
- `search_rebuild`
- `media_verify`
- `derivative_rebuild` (CLI initially; API may be added)
- `backup_create`
- `backup_verify`

Jobs expose progress current/total where countable, bounded result summary, safe error, actor, timestamps, and cancellation policy. Heavy work batches records and yields between transactions so normal reads/writes remain available.

## 14. Disk management

Thresholds are based on both percentage and absolute reserve:

- warning below 15% free or 10 GiB;
- write degradation below 8% or 5 GiB;
- uploads/analysis/backup rejected below 5% or 2 GiB;
- ordinary reads/search remain available unless SQLite itself cannot operate.

Cleanup candidates are stale staging files, rebuildable derivatives, expired sessions/idempotency records, old failed diagnostics, then owner-approved old verified backups. Originals and the last verified backup are never automatically deleted.

## 15. Diagnostic bundle

Owner may generate a local diagnostic archive containing release/schema versions, non-secret config categories, service health, redacted recent logs, DB integrity/row counts, queue summary, storage counts/bytes, model manifest/checksums, and search/media verify summaries.

It excludes credentials, secrets, CA private keys, images, descriptions, item names/notes, search queries, raw model output, and absolute host paths. The UI warns that even redacted diagnostics may reveal operational metadata.

## 16. Runtime-offline verification

Release qualification runs the production bundle in a network namespace where:

- local client-to-Boxen traffic is allowed;
- private container traffic is allowed;
- default route/DNS/public egress is denied and logged;
- no cached public responses are available.

The full core acceptance suite, AI evaluation smoke, label rendering, camera/upload scanner fixture, backup, restart, and restore smoke must pass. Any attempted external connection fails the release.

## 17. Operational ownership

The owner is responsible for host physical security, operating-system/container updates, disk encryption, trusted client devices, CA root distribution/removal, backup media protection, and periodic restore rehearsal. Boxen reports actionable status but does not pretend to manage the host OS.
