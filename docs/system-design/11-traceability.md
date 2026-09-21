# Requirements Traceability

This matrix links every v1 requirement to its primary normative design and minimum verification evidence. Detailed subtests may add evidence but cannot replace these rows.

## Functional requirements

| ID | Primary design | Minimum evidence |
| --- | --- | --- |
| FR-001 | DDD `Box`; API `POST /boxes`; UI Create/Edit | `T-DOM-BOX-003`, `T-E2E-002` |
| FR-002 | `BoxCode` value object; schema unique code | `T-DOM-CODE-001..006`, `T-DB-004` |
| FR-003 | Box lifecycle/purge invariants; archive/restore/purge API | `T-DOM-BOX-001..002`, `T-E2E-008` |
| FR-004 | Box composed read model; Box Detail UI | `T-API-001`, `T-UI-001`, `T-E2E-002` |
| FR-005 | Markdown value/service; stored source/html/text | `T-MD-001..004`, `T-E2E-002` |
| FR-006 | Image aggregate; multipart upload; capture UI | `T-MEDIA-001`, `T-E2E-003` |
| FR-007 | Media saga, validation, derivatives, storage contract | `T-MEDIA-001..008`, fault injection |
| FR-008 | Image caption/order/remove commands and UI | `T-MEDIA-006..007`, `T-E2E-003` |
| FR-009 | Inventory aggregate CRUD/merge | `T-DOM-ITEM-001..003`, `T-E2E-005` |
| FR-010 | Quantity/notes value rules and API schemas | `T-DOM-ITEM-001`, `T-MD-*`, `T-API-001` |
| FR-011 | Analysis request API/job aggregate | `T-DOM-AI-001`, AI adapter tests, `T-E2E-004` |
| FR-012 | Web/worker separation and durable queue | `T-DB-010`, job fault injection, `T-E2E-004` |
| FR-013 | Immutable run/observation provenance and AI schema | `T-DOM-AI-*`, JSON schema tests, AI evaluation |
| FR-014 | Observation state/accept/merge/reject UI/API | `T-DOM-AI-003..004`, `T-E2E-004` |
| FR-015 | Human-reviewed AI ADR/domain invariant | `T-DOM-AI-005`, authorization/domain tests |
| FR-016 | Degradation matrix | `T-E2E-011`, runtime failure injection |
| FR-017 | FTS search document/query spec | search suite, `T-DB-008..009`, `T-E2E-005` |
| FR-018 | Exact-code and BM25 ranking policy | search ranking fixtures/performance suite |
| FR-019 | Search response/UI screen spec | OpenAPI conformance, `T-UI-001`, search E2E |
| FR-020 | Search verify/rebuild jobs | `T-DB-009`, maintenance E2E |
| FR-021 | Label renderer/profile/PDF API/UI | `T-E2E-006`, digital/physical label suite |
| FR-022 | Canonical QR ADR/payload codec | parser property/fuzz and physical tests |
| FR-023 | Scan live/upload/type UI and resolve API | `T-UI-009`, `T-E2E-007`, device matrix |
| FR-024 | Scanner error taxonomy/UI states | component states, parser/API negative E2E |
| FR-025 | User aggregate/role APIs/system UI | `T-DOM-IAM-*`, `T-API-003`, `T-E2E-010` |
| FR-026 | System status and health model | operations integration and `T-UI-001` |
| FR-027 | Backup coordinator/manifest/verify | `T-E2E-013`, backup integrity tests |
| FR-028 | Offline restore CLI/runbook | restore fault/drill, `T-E2E-013..014` |
| FR-029 | Append-only audit schema/handlers | `T-DB-004`, security audit-event tests |

## Non-functional requirements

| ID | Primary design | Minimum evidence |
| --- | --- | --- |
| NFR-001 | Runtime-offline architecture/operations | `T-E2E-015`, denied-egress attempt capture |
| NFR-002 | Build/dependency/security locality rules | `T-ARCH-003..004`, frontend/network scan |
| NFR-003 | Single-host topology/ADR | deployment topology inspection/test |
| NFR-004 | SQLite authority/DDL | `T-DB-001..012` |
| NFR-005 | Managed media authority/keys | `T-MEDIA-*`, media integrity scan |
| NFR-006 | WAL/full-sync/transactions | `T-DB-006..007`, crash injection |
| NFR-007 | Backup format and consistency | `T-E2E-013`, checksum/media completeness |
| NFR-008 | RPO/RTO operations targets | scheduled-backup and timed restore drill |
| NFR-009 | API performance targets | capacity performance table |
| NFR-010 | Search performance target | capacity search p95/p99 report |
| NFR-011 | UI first-content target | browser performance trace on phone/Wi-Fi fixture |
| NFR-012 | QR resolve target | scanner device timing matrix |
| NFR-013 | Async AI responsiveness | `T-E2E-004`, UI responsiveness trace |
| NFR-014 | 320 px responsive floor | `T-UI-005`, visual regression matrix |
| NFR-015 | WCAG 2.2 AA | `T-UI-003..006`, manual device/screen-reader audit |
| NFR-016 | Browser compatibility | release browser/device matrix |
| NFR-017 | HTTPS camera + alternatives | `T-UI-009`, target-device camera/upload/type tests |
| NFR-018 | OWASP ASVS 5 L2 subset | security evidence matrix, no critical/high findings |
| NFR-019 | Argon2id credentials | hasher vectors/parameter benchmark/security tests |
| NFR-020 | Testable boundaries/contracts | architecture tests, API/port fakes, suite inventory |
| NFR-021 | Pinned artifacts | `T-ARCH-004`, manifest/checksum/SBOM verification |
| NFR-022 | Forward migration safety | `T-DB-001..003`, `T-E2E-014`, rollback drill |

## Original request coverage

| Requested capability | Requirement IDs |
| --- | --- |
| Track boxes, contents, and images | FR-001..010 |
| Local AI image inventory | FR-011..016 |
| User Markdown description | FR-001, FR-005, FR-010 |
| Printable QR/name/typeable-code label | FR-021..022 |
| SQLite database | NFR-004, NFR-006, NFR-022 |
| Search titles and contents | FR-017..020 |
| Responsive phone UI | NFR-014..017 |
| No non-local runtime resource | NFR-001..003, NFR-021 |
| Scan/upload QR and find contents | FR-023..024 |

## Traceability maintenance rule

Every pull request that changes a requirement, endpoint, aggregate invariant, schema, screen behavior, security control, or release gate MUST update the corresponding design, contract, tests, and this matrix. CI checks that every declared FR/NFR/Test ID referenced here exists exactly once in its authoritative source.
