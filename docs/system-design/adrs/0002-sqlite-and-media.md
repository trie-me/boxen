# ADR-0002: SQLite plus managed local media

- **Status:** Proposed for v1 baseline
- **Date:** 2026-09-20

## Context

The product requires SQLite, multiple images, local-only operation, simple backup, and search. Storing many image binaries as SQLite BLOBs would enlarge page/WAL/backup churn; storing loose files without a transactional catalog risks orphaning and inconsistent backup.

## Decision

Use SQLite as the authoritative structured database and a managed content-addressed local filesystem for original/derived image bytes. SQLite records hashes, storage keys, lifecycle, and relationships. Upload/removal use explicit recoverable sagas. Backup snapshots SQLite and referenced originals under one manifest/checksum set.

## Consequences

- Relational state/search remain compact and transactional.
- Media streaming/derivatives do not inflate SQLite write amplification.
- Backup/restore and deletion require coordinated logic and integrity checks.
- A network filesystem and multi-host writers are unsupported.
- Derivatives/search can be rebuilt; originals and SQLite cannot.

## Rejected alternatives

- **All BLOBs in SQLite:** simple single file but poor large-media write/backup characteristics.
- **Filesystem metadata only:** cannot enforce lifecycle, provenance, search, or consistency.
- **S3-compatible store:** violates minimal local runtime and adds unnecessary operations.

