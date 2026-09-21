# Test and Quality Plan

> Scope correction: [ADR-0005](adrs/0005-small-local-app-and-anonymous-access.md) removes capacity/load benchmarks as build or release gates. References to large datasets and concurrency qualification below are historical, not required work. Functional, security, recovery, offline, and normal mobile-use checks remain applicable.

## 1. Quality strategy

Tests provide evidence against requirement IDs, domain invariants, machine-readable contracts, threats, and operational recovery. The strategy favors deterministic tests at the lowest useful layer, then exercises complete local workflows on the production bundle.

No release is accepted solely by code coverage or a successful happy-path demo.

## 2. Test layers

| Layer | Scope | Runtime target |
| --- | --- | --- |
| Static/architecture | Types, lint, dependency boundaries, secrets, licenses, contract lint | Every change |
| Domain unit/property | Value objects, aggregate commands, invariants, state machines | Every change |
| Persistence integration | Real SQLite, migrations, transactions, FTS5, jobs | Every change |
| Adapter/contract | HTTP OpenAPI, filesystem, Markdown, PDF/QR, fake/real AI adapter | Every change / nightly split |
| Frontend component | Rendering, accessibility, interactions, API state handling | Every change |
| End-to-end | Browser through production-like stack | Every change core; full nightly |
| Device/physical | Phone camera, print/scan, certificate trust, accessibility | Release candidate |
| AI evaluation | Private labeled image corpus on each profile | Profile/release change |
| Security/performance/recovery | Threat controls, capacity, fault/restart, backup/restore | Nightly/release candidate |
| Offline acceptance | Production bundle with all public egress denied | Release candidate |

## 3. Test environments

### `unit`

No filesystem/network/database. Frozen clock, deterministic UUID/code/random ports, in-memory fakes. Runs in seconds.

### `integration`

Temporary local directory and real SQLite build with FTS5/JSON enabled. Uses actual migration files and filesystem adapter, fake model process. Runs per change.

### `system`

Production containers, local TLS, real browser, reference-sized deterministic dataset, fake AI by default. Public egress may be denied. Runs core per change and full nightly.

### `ai-profile`

Qualified hardware plus actual pinned model/runtime and private image corpus. Never runs against production user data.

### `device-lab`

At least one current iPhone/Safari, one current Android/Chrome, and desktop Chrome/Firefox/Safari or Edge as platform permits; real local CA enrollment and label printer.

## 4. Test data policy

- Synthetic users, box descriptions, item names, Markdown, and generated media fixtures are deterministic and non-sensitive.
- Malicious/security fixtures are isolated and clearly labeled.
- AI corpus is private, consented, versioned, checksum-manifested, and excluded from ordinary source distributions when licensing/privacy requires.
- No production backup/image/database is copied into CI.
- Capacity datasets are generated from a seed and record generator version.
- Tests never depend on execution order, wall clock, external DNS, or internet content.

## 5. Static and architecture tests

| ID | Evidence |
| --- | --- |
| `T-ARCH-001` | Domain packages have no FastAPI/SQLAlchemy/filesystem/model imports |
| `T-ARCH-002` | HTTP/worker adapters call application services and do not issue SQL directly |
| `T-ARCH-003` | Frontend production bundle has no remote URL/import/font/analytics reference |
| `T-ARCH-004` | Dependency and container locks contain no floating versions/tags |
| `T-ARCH-005` | OpenAPI, SQL, JSON Schema, model manifests, Compose, and CSS tokens parse/lint |
| `T-ARCH-006` | Generated API client compiles and operation IDs are unique/implemented |
| `T-ARCH-007` | Secret scanner and committed-file policy pass |
| `T-ARCH-008` | SBOM and required licenses/notices are generated |

## 6. Domain unit and property tests

### Box code

- `T-DOM-CODE-001`: generated codes match canonical format and checksum.
- `T-DOM-CODE-006`: normative vector `7K3MR9Q → A → BX-7K3M-R9QA → boxen:v1:BX-7K3M-R9QA` matches in backend, frontend worker, OpenAPI examples, and label fixtures.
- `T-DOM-CODE-002`: 1,000,000 deterministic generations produce no unexpected collision under allocator retry contract.
- `T-DOM-CODE-003`: parser property round-trips canonical/flexible case/separator input.
- `T-DOM-CODE-004`: exhaustive one-symbol mutations match the specified checksum function and measured false-accept rate remains at the expected 1/32 bound.
- `T-DOM-CODE-005`: invalid Unicode/confusable/overlength input fails boundedly.

### Catalog and inventory

- `T-DOM-BOX-001`: lifecycle transition matrix allows only active↔archived and guarded purge.
- `T-DOM-BOX-002`: archived box rejects all content/media/inventory/analysis mutations.
- `T-DOM-BOX-003`: name/Markdown boundaries and version increments.
- `T-DOM-ITEM-001`: quantity thousandths conversions round-trip and reject zero/negative/overflow/precision loss.
- `T-DOM-ITEM-002`: merge conserves explicit result/links and rejects cross-box or incompatible implicit units.
- `T-DOM-ITEM-003`: provenance transitions manual/ai→mixed correctly after user edit.

### Analysis

- `T-DOM-AI-001`: job state/lease transition model checked exhaustively.
- `T-DOM-AI-002`: lease expiry/redelivery cannot produce duplicate terminal completion.
- `T-DOM-AI-003`: observation decision is one-way/idempotent for same outcome and conflicting otherwise.
- `T-DOM-AI-004`: acceptance atomically maps quantity, provenance, and same-box item link.
- `T-DOM-AI-005`: re-analysis creates new observations and leaves accepted/user-edited inventory unchanged.

### Identity

- `T-DOM-IAM-001`: last active owner cannot be disabled/demoted.
- `T-DOM-IAM-002`: credential change increments version and invalidates prior session version.
- `T-DOM-IAM-003`: role policy table has explicit allow/deny for every command.

Mutation testing is required for BoxCode, lifecycle, authorization, observation acceptance, and inventory merge modules. Surviving non-equivalent mutants block release.

## 7. Persistence and migration tests

Run against the same SQLite compilation/options as production.

- `T-DB-001`: apply all migrations to empty DB; schema matches expected canonical introspection.
- `T-DB-002`: upgrade every supported release fixture to current; source data/provenance/search remain correct.
- `T-DB-003`: interrupted resumable migration restarts safely at each journaled boundary.
- `T-DB-004`: foreign key, strict type, check, uniqueness, and append-only triggers reject invalid writes.
- `T-DB-005`: application invariants not expressible in SQL are enforced transactionally under concurrent commands.
- `T-DB-006`: busy/lock contention returns bounded retry/problem, never deadlock or partial commit.
- `T-DB-007`: WAL checkpoint/restart/crash simulation preserves committed transactions.
- `T-DB-008`: search source mutation and FTS result are read-after-write consistent.
- `T-DB-009`: verify finds injected FTS drift; rebuild restores exact source hash/count/ranking fixtures.
- `T-DB-010`: job claim/lease/redelivery and idempotent completion with two worker processes.
- `T-DB-011`: purge/tombstone/media references/audit maintain referential policy.
- `T-DB-012`: database at capacity dataset passes `integrity_check` and foreign-key check.

## 8. Media and Markdown tests

### Media

- `T-MEDIA-001`: valid JPEG/PNG/WebP signatures, orientation, dimensions, checksums, and derivatives.
- `T-MEDIA-002`: extension/MIME mismatch uses byte signature; unsupported/animated formats rejected.
- `T-MEDIA-003`: compressed-size, dimension, pixel, frame, decode-time, and memory limits.
- `T-MEDIA-004`: known decompression-bomb/polyglot/corrupt/truncated corpus fails safely.
- `T-MEDIA-005`: filename/path traversal and Unicode filename cases never influence storage path/headers.
- `T-MEDIA-006`: crash/failure at every upload-saga boundary leaves recoverable DB/files.
- `T-MEDIA-007`: duplicate same-box hash returns existing image; cross-box shared storage cleanup respects references.
- `T-MEDIA-008`: metadata stripped from derivatives; original access role-protected.

### Markdown

- `T-MD-001`: CommonMark conformance subset and stable renderer snapshots.
- `T-MD-002`: stored/reflected/DOM XSS corpus sanitized; raw HTML/external images removed.
- `T-MD-003`: dangerous schemes, malformed URLs/Unicode, parser differential cases.
- `T-MD-004`: rendered HTML/plain text/search projection update together by renderer version.

## 9. API and contract tests

Every OpenAPI operation has success, unauthenticated, unauthorized, validation, not-found, lifecycle, and documented precondition cases as applicable.

- `T-API-001`: live response bodies/headers/statuses validate against OpenAPI.
- `T-API-002`: unknown mutation fields, duplicate JSON keys, invalid UTF-8/depth/size rejected.
- `T-API-003`: role matrix viewer/editor/owner for every operation.
- `T-API-004`: cookie attributes, login generic failure, expiry/rotation/revocation/credential version.
- `T-API-005`: CSRF token and exact-Origin enforcement; CORS absent.
- `T-API-006`: ETag required/stale/current behavior and conflict payload.
- `T-API-007`: idempotency replay returns same result; conflicting hash/key returns stable conflict.
- `T-API-008`: cursor tamper, limits, stable ordering under inserts, end-of-page behavior.
- `T-API-009`: RFC 9457 shape, safe detail, request ID, field paths, retry headers.
- `T-API-010`: upload streaming/limits/disconnect and no request-buffer memory spike.
- `T-API-011`: media authorization/content type/cache/nosniff/original restrictions.
- `T-API-012`: job polling ETag/304/backoff contract and terminal links.
- `T-API-013`: breaking-change diff against last released v1 OpenAPI.

## 10. Frontend component and accessibility tests

- `T-UI-001`: every route renders loading, populated, empty, partial-error, session-expired, and unauthorized state.
- `T-UI-002`: forms associate labels/help/errors, focus first error, preserve user values, and prevent duplicate submit.
- `T-UI-003`: keyboard tab/order/activation/escape/focus return for navigation, dialogs, editor, review, gallery, scan alternatives.
- `T-UI-004`: automated WCAG checks with no critical/serious violations; manual checks remain mandatory.
- `T-UI-005`: 320/375/768/1024/1440 layouts have no overlap, clipped controls, page horizontal scroll, or obscured focus.
- `T-UI-006`: 200% zoom, text spacing overrides, forced colors, reduced motion.
- `T-UI-007`: API slow/fail/retry/stale ETag/offline host behavior preserves drafts and explains state.
- `T-UI-008`: cyberpunk tokens used semantically; color-independent states and contrast calculations pass.
- `T-UI-009`: scanner stops camera tracks on success/stop/route change/background; permission errors expose alternatives.
- `T-UI-010`: no network request leaves configured origin during all component/e2e flows.

Use visual regression baselines for the application shell, box list/detail, AI review, scanner states, label preview, and system status at desktop/mobile reference widths. Baselines are reviewed, not blindly updated.

## 11. End-to-end acceptance scenarios

| ID | Scenario |
| --- | --- |
| `T-E2E-001` | First-run owner setup → login → logout → login |
| `T-E2E-002` | Create box with Markdown → immediate exact/name/description search |
| `T-E2E-003` | Mobile photo upload → gallery derivative → remove/reorder |
| `T-E2E-004` | Fake deterministic AI queue → restart worker → observations → accept/edit/merge/reject |
| `T-E2E-005` | Manual item create/edit/remove/restore/merge → search consistency |
| `T-E2E-006` | Label PDF fixture → decode QR → exact name/code/layout assertions |
| `T-E2E-007` | Live scanner fixture/upload QR/typed code all resolve same box |
| `T-E2E-008` | Archive blocks mutations, hides default search, scan reports archived, restore re-enables |
| `T-E2E-009` | Two sessions stale edit → 412 → conflict recovery without lost draft |
| `T-E2E-010` | Viewer/editor/owner complete allowed tasks and receive denials for forbidden tasks |
| `T-E2E-011` | AI unavailable: core app remains healthy and prior observations reviewable |
| `T-E2E-012` | Disk low: writes requiring space denied; reads/search/exported label remain available |
| `T-E2E-013` | Backup create/verify → mutate → offline restore → exact pre-mutation state |
| `T-E2E-014` | Upgrade prior schema fixture → smoke all core flows and rollback rehearsal |
| `T-E2E-015` | Full acceptance with public egress/DNS denied |

## 12. Search tests

- Exact code always first and case/separator normalization works.
- Name and item-name fixtures outrank description and item-note-only fixtures.
- Unicode, diacritics, punctuation, phrase/prefix policy, empty/stopword/overlength input.
- Malicious/raw FTS syntax is treated as text or safely rejected.
- Snippet ranges map to returned plain text and never contain executable HTML.
- Create/edit/accept/merge/remove/archive/restore/purge mutations update visibility immediately.
- Capacity dataset p50/p95/p99 and query-plan regression are recorded.

## 13. AI tests

### Adapter and schema

- Fake runtime success/error/timeout/cancel/oversize/invalid UTF-8/invalid JSON/schema violation.
- Exact model/prompt/schema/preprocessing provenance stored.
- No remote URL/tool/filesystem path outside allowlist can be requested.
- Prompt-injection image text remains data and output cannot trigger action.
- Retry taxonomy and maximum attempts match the specification.

### Evaluation

- Run the full labeled corpus for every release-qualified profile.
- Compute precision, recall, unsupported suggestion, count accuracy, duplicate rate, empty-scene false positive, schema validity, crash/hang, latency, and peak memory.
- Report per slice and confidence calibration; compare to previous release with regression thresholds.
- Human-review a random sample plus every unsupported suggestion.
- Model/runtime/prompt/schema/preprocessing changes require the full gate, not smoke only.

## 14. QR and physical label tests

### Digital fixtures

- Canonical payload round-trip, checksum/version/length/parser fuzzing.
- QR decode after PNG/PDF render, deterministic PDF hash except declared metadata.
- Long/Unicode/RTL box names, minimum/maximum code/name, embedded fonts.
- PDF page physical size and QR quiet zone/module size measured programmatically.

### Physical matrix

- Every supported label profile on at least one target printer at 100% scale.
- Scan with target iPhone and Android under bright, dim, angled, 30-100 cm, minor wrinkle/smudge conditions.
- Five labels per profile; zero wrong-box decode accepted.
- System camera behavior may be observed, but in-app live/upload/manual are normative.

## 15. Performance and capacity tests

Dataset: 10,000 boxes, 100,000 active items, 50,000 image metadata rows with representative derivative files, 100,000 observations/runs, 10 concurrent sessions.

| Workload | Gate on reference hardware |
| --- | --- |
| Box detail read | p95 < 250 ms, p99 < 500 ms |
| Box/list pagination | p95 < 250 ms |
| Search common/rare/exact code | p95 < 250 ms, p99 < 500 ms |
| Catalog/item mutation | p95 < 500 ms excluding upload |
| Session/login | p95 < 1 s including password hash |
| 25 MiB upload | streaming memory bounded; no whole-file duplicate buffer |
| 10 mixed concurrent users | error rate < 0.1%, no starvation |
| FTS rebuild | completes with reads available; time recorded as release trend |
| Backup | completes within RTO budget and normal read p95 < 2× baseline |

Performance tests warm expected caches, also record cold start, and fail on material regression even when absolute gate still passes unless reviewed.

## 16. Resilience and recovery tests

Inject process kill/power-loss-equivalent points at upload saga steps, job lease/AI response/completion, inventory acceptance transaction, backup stages, migration journal, FTS rebuild swap, and graceful shutdown.

Evidence:

- committed state survives;
- uncommitted state is absent or reconciled;
- no duplicate accepted inventory/run;
- stale leases recover;
- staging/orphan files are safely identified;
- integrity check passes;
- user receives bounded actionable state.

Restore drills run at least once per release candidate from the newest verified backup and one oldest-supported backup fixture.

## 17. Security tests

- OWASP ASVS 5.0 scoped checklist with test/evidence links.
- Auth/session/CSRF/origin/rate-limit/authorization abuse.
- Stored/reflected/DOM XSS, SQL/FTS/command/path/header injection.
- Upload polyglot/bomb/corrupt/metadata and content-sniffing cases.
- QR malicious URL/script/oversize/version cases.
- AI prompt/output injection and runtime isolation.
- Dependency/container/model checksum tamper.
- Secret/log/diagnostic redaction.
- Container least privilege, mounts, capabilities, published ports, egress.
- Backup tamper/missing media/wrong installation/schema and quarantine recovery.

Dynamic scanners may supplement but never replace domain-specific manual tests.

## 18. Coverage and flake policy

- Critical domain modules target 90% branch coverage; overall changed-code target 80%.
- Coverage is diagnostic; invariant/requirement evidence matters more than line count.
- No test is retried automatically to hide failure.
- A flaky test is quarantined only with owner, linked defect, expiry, and equivalent release evidence; critical security/data tests cannot be quarantined.
- Time/randomness/concurrency are controlled through ports and deterministic schedulers where possible.

## 19. Release gates

A release candidate is rejected unless all are true:

1. All FR/NFR rows have passing evidence or explicit approved deferment outside v1.
2. Static, domain, DB, contract, frontend, and core E2E suites pass.
3. Full supported migration matrix and backup/restore drill pass.
4. Runtime-offline suite records zero external attempts.
5. Security gate has no unresolved critical/high finding.
6. UI device/accessibility and physical QR matrix pass.
7. Every bundled AI profile passes quality/resource gates.
8. Capacity/performance gates pass with archived trend report.
9. SBOM/licenses/checksums/release manifest are complete.
10. Operations documentation is exercised by someone other than its author.
