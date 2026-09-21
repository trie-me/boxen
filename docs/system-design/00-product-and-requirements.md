# Product and Requirements

> Current scope: [ADR-0005](adrs/0005-small-local-app-and-anonymous-access.md) supersedes the capacity targets and account-required default in this original baseline. This is a single/low-user local app with configurable anonymous access; large-dataset and concurrency qualification is not required.

## 1. Scope

Boxen v1 is a local inventory system for physical storage boxes. It is optimized for one household, studio, workshop, archive, or small trusted team. It is not a cloud service, distributed database, generic warehouse-management platform, or autonomous AI cataloger.

## 2. Personas and authorization

| Persona | Goal | v1 role |
| --- | --- | --- |
| Owner | Configure, protect, back up, restore, and fully manage Boxen | `owner` |
| Editor | Create boxes, attach images, curate inventory, print labels | `editor` |
| Viewer | Search, browse, scan, and read box contents | `viewer` |

A fresh installation creates exactly one owner through a local first-run flow. The owner MAY create local editor/viewer accounts. No external identity provider is required or supported in v1.

## 3. Ubiquitous terms

| Term | Meaning |
| --- | --- |
| Box | A physical container represented by one stable record |
| Box code | Immutable, human-typeable public identifier printed on a label |
| Description | User-authored CommonMark content describing a box |
| Image asset | Validated original image and its locally generated derivatives |
| Inventory item | Human-confirmed record of an item or item group in a box |
| Observation | AI-proposed item found in one image; not inventory until accepted |
| Analysis run | One immutable attempt by one model/prompt version on one image |
| Label | Printable representation of box name, box code, and canonical QR payload |
| Search document | Rebuildable FTS projection of one box and its confirmed contents |
| Runtime offline | No request to a non-local resource is necessary after provisioning |

## 4. Functional requirements

### Catalog

- **FR-001:** An editor MUST be able to create a box with a required name and optional Markdown description.
- **FR-002:** The system MUST assign every box one unique, immutable `BoxCode` at creation.
- **FR-003:** An editor MUST be able to rename, edit, archive, and restore a box. Archived boxes MUST be read-only except for restore and permanent-delete administration.
- **FR-004:** A viewer MUST be able to open a box by code and see its description, images, confirmed inventory, and pending-analysis status.
- **FR-005:** Markdown MUST be stored as source, rendered safely, and converted to plain text for search.

### Images and inventory

- **FR-006:** An editor MUST be able to capture or upload JPEG, PNG, or WebP images and associate them with one box.
- **FR-007:** The system MUST validate, orient, checksum, persist, thumbnail, and serve images locally.
- **FR-008:** An editor MUST be able to reorder, caption, and remove an image.
- **FR-009:** An editor MUST be able to create, edit, merge, move within the same box, and delete confirmed inventory items.
- **FR-010:** Inventory items MUST support name, optional quantity, optional unit, and optional Markdown notes.

### Local AI

- **FR-011:** An editor MUST be able to request local AI analysis for an eligible image.
- **FR-012:** Analysis MUST run asynchronously without blocking catalog reads/writes.
- **FR-013:** AI output MUST be schema-validated and stored as observations tied to image, run, model checksum, and prompt version.
- **FR-014:** Pending observations MUST be individually or bulk accepted, edited-and-accepted, merged into an existing item, or rejected.
- **FR-015:** AI MUST NOT directly alter confirmed inventory or overwrite user-authored values.
- **FR-016:** Failed or unavailable AI MUST leave all non-AI application capabilities operational.

### Search

- **FR-017:** A viewer MUST be able to search active boxes by box code, name, description text, confirmed item name, and confirmed item notes.
- **FR-018:** Exact box-code matches MUST rank first. Name/item matches MUST rank above description/note-only matches.
- **FR-019:** Search results MUST identify the box, code, matched field/snippet, matching items, and a representative thumbnail when available.
- **FR-020:** The owner MUST be able to verify and rebuild the search projection without changing source records.

### QR labels and lookup

- **FR-021:** An editor MUST be able to preview and produce a PDF label containing the box name, exact typeable code, and QR symbol.
- **FR-022:** The QR symbol MUST encode `boxen:v1:<BoxCode>` and use error-correction level Q or better when label dimensions permit.
- **FR-023:** A viewer MUST be able to resolve a box through live camera scan, uploaded QR image, or typed code.
- **FR-024:** Invalid payload, unsupported payload version, invalid checksum, unknown box, and archived box MUST produce distinct recoverable UI states.

### Administration

- **FR-025:** The owner MUST be able to create and disable local users and assign one of the three v1 roles.
- **FR-026:** The owner MUST be able to view component health, database/media usage, model readiness, failed jobs, and backup status.
- **FR-027:** The owner MUST be able to create a consistent backup and verify it.
- **FR-028:** Restore MUST be an explicit offline administrative operation with preflight and post-restore verification.
- **FR-029:** Security-relevant and destructive actions MUST create an append-only audit entry.

## 5. Non-functional requirements

### Locality and privacy

- **NFR-001:** After installation and model provisioning, all acceptance scenarios MUST pass with internet egress and DNS blocked.
- **NFR-002:** No telemetry, remote font, CDN, hosted analytics, external update check, or cloud model API MAY be present in runtime code paths.
- **NFR-003:** The web, worker, AI, database, media, backup, and TLS assets MUST reside on one administered local host.

### Storage and durability

- **NFR-004:** SQLite MUST be the authoritative structured datastore.
- **NFR-005:** Original images and derivatives MUST be on a local filesystem managed by storage keys recorded in SQLite.
- **NFR-006:** Successful writes MUST survive process restart and host reboot after the operating system reports durable completion.
- **NFR-007:** Backups MUST contain a consistent SQLite snapshot, every referenced original, configuration manifest, and checksum inventory.
- **NFR-008:** Default recovery objectives are RPO 24 hours and RTO 2 hours when daily verified backups are configured.

### Performance

- **NFR-009:** On reference hardware and the capacity dataset, non-upload API reads SHOULD have p95 latency below 250 ms and writes below 500 ms.
- **NFR-010:** Search SHOULD have p95 latency below 250 ms for 10,000 boxes/100,000 confirmed items.
- **NFR-011:** First meaningful UI content SHOULD render within 2 seconds on a modern phone over ordinary local Wi-Fi after assets are cached.
- **NFR-012:** A valid QR SHOULD resolve and navigate within 2 seconds after decode.
- **NFR-013:** AI latency is profile-dependent; the UI MUST remain responsive and show durable progress regardless of inference time.

### Compatibility and accessibility

- **NFR-014:** The UI MUST function at widths from 320 CSS px upward without horizontal page scrolling.
- **NFR-015:** Core flows MUST conform to WCAG 2.2 AA, including keyboard access, focus visibility, target size, contrast, reduced motion, labels, and error identification.
- **NFR-016:** Supported clients are the current and previous major releases of Safari on iOS, Chrome on Android, and Chrome/Firefox/Edge/Safari on desktop at release time.
- **NFR-017:** Live camera capability MUST use local HTTPS; upload and typed-code alternatives MUST remain available.

### Security and maintainability

- **NFR-018:** The application MUST meet the scoped OWASP ASVS 5.0 Level 2 controls enumerated in the security specification.
- **NFR-019:** Passwords MUST be hashed with Argon2id using parameters benchmarked on the host and never logged or exported in ordinary data exports.
- **NFR-020:** Every externally visible entity and state transition MUST be testable through a stable application boundary.
- **NFR-021:** All dependencies, container bases, model files, prompt templates, and schemas MUST be pinned by version or digest.
- **NFR-022:** Database migrations MUST be forward-only, transactional where SQLite permits, restart-safe, and covered by upgrade/backup tests.

## 6. Use-case acceptance summaries

### UC-01 Catalog a box

Given an authenticated editor, when they create a box named “Darkroom Gear,” then a unique code is assigned, the empty detail view is returned, and a search for the exact name finds it immediately.

### UC-02 Photograph and analyze contents

Given an active box, when an editor uploads a valid image and requests analysis, then the upload returns before inference completes, a durable job becomes visible, and successful output appears only as pending observations.

### UC-03 Curate AI output

Given pending observations, when an editor accepts, edits, merges, or rejects each result, then confirmed inventory and search change only according to those decisions and later re-analysis does not overwrite them.

### UC-04 Print and retrieve

Given an active box, when an editor prints its label, then the rendered name and code match the box and the QR decodes to the canonical payload. Scanning live, decoding an uploaded QR image, or typing the code retrieves the same box.

### UC-05 Operate disconnected

Given a fully provisioned installation with outbound traffic denied, every catalog, image, AI, search, label, scan, user, health, and backup acceptance scenario succeeds locally.

## 7. Explicit non-goals for v1

- Multi-host active/active operation or network filesystem storage.
- Cloud sync, remote backup providers, public sharing, or internet-facing deployment.
- Native mobile apps or browser operation while disconnected from the Boxen host.
- Automated item valuation, purchase lookup, OCR document archiving, or warranty tracking.
- Visual similarity lookup of an unlabelled box.
- AI auto-acceptance, face recognition, or analysis of video/audio.
- Nested boxes, warehouses, bins, check-in/out, reservations, or item-level QR labels.

## 8. Deployment inputs and controlled variance

The architecture has no unresolved dependency on deployment choices. The release baseline is the Linux/container reference host, 10,000-box capacity dataset, built-in label profiles, documented current/previous browser matrix, enabled local multi-user roles, and both connected and removable-media model provisioning. An installation MAY select different hardware, collection size, stock, or client devices, but those become declared deployment inputs and the applicable performance, print, camera, backup, and AI qualification suites MUST be rerun before production use.
