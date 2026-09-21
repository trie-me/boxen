# Storage/backup sidecar review — 2026-09-20

Scope was narrowed by the coordinating build task to confirmed high-priority correctness fixes and focused tests for immediate integration. No schema, API, CLI, other backend modules, existing tests, or production data were changed by this sidecar. Main owns the CLI runtime-lock changes.

## Changed paths and behavior

- `backend/boxen/operations/infrastructure/backup.py`: verifies exact correspondence between checksum-list entries and manifest files, file counts and total bytes; rejects malformed metadata, duplicate JSON keys, path aliases and symlinks in file/parent paths; checks snapshot installation and packaged migration checksum, plus original sizes/hashes. Opens snapshot SQLite through an escaped, read-only immutable URI so unchecked WAL sidecars cannot influence verification. Flushes backup payloads and directories before publishing the manifest and makes files owner-only.
- The same file: restore copies only manifest-listed database/media files and verifies destination bytes before moving live data. Unlisted media and symlinks are not imported into active media. The configured database location is preserved. The existing runtime-lock inode is linked into the restored root so activation does not replace the held lock with an unlocked inode. Restored database writes use FULL synchronization; relevant directories are synchronized. Existing source data remains in quarantine.
- `backend/boxen/operations/application.py`: a process-shared coordinator lock covers operation selection through terminal persistence, preventing simultaneous CLI/worker runners from marking each other's backup failed. Contention with orphan reconciliation on `backup.lock` leaves a pending backup unchanged for retry.
- `backend/tests/test_storage_security.py`: 17 regression cases covering manifest totals, missing/duplicate/extra/incorrect checksum entries, symlinked metadata/parents, duplicate JSON fields, snapshot identity/schema mismatch, special characters in SQLite paths, unchecked restore files, copy corruption, lock-inode preservation, concurrent runners, and backup-lock contention.

## Verification

`.venv/bin/pytest backend/tests/test_storage_security.py backend/tests/test_recovery.py backend/tests/test_ai_operations.py`: **25 passed**, with two existing dependency deprecation warnings. Ruff formatting and lint passed on all three changed Python files. This is targeted verification, not a claim that the entire suite or release qualification was rerun. Main reported 121 backend and 7 browser tests passing before integration.

## Remaining concrete concerns

- `backup_retention` is still configuration-only. No automatic retention or deletion was introduced. Failed/incomplete roots and quarantine can accumulate; original bytes and retained generations remain recoverable.
- Restore retains models and backup history through hardlinks. Those copies are not independent snapshots if later code modifies files in place. Interrupted backup creation can reuse an existing destination directory; a separate recovery policy should quarantine partial generations before reuse.
- Restore still uses two directory renames. A host crash between them requires recovery from the sibling restore/quarantine roots; this patch does not introduce a durable activation journal. Failed preparation leaves its sibling directory for inspection.
- Integration follow-up: main added expiry/state/token fencing to maintenance renewal, projection transactions and terminal writes. A regression test proves an expired rebuild rolls back and cannot publish a terminal result. Broader analysis review remains outside this sidecar.
- Worker scheduling measures the newest backup attempt, including failures, rather than the last verified generation; it also does not implement the specified 02:00 local schedule. Session/idempotency bulk expiry cleanup and bounded quarantine retention remain incomplete.
- Checksums detect inconsistency, not authenticity against an attacker who replaces a complete backup and recomputes all hashes. Verification is not tied to an independently trusted signature. Host-compromise and continuously hostile filesystem races are not solved by these changes.
- CLI operation lifetime locks were fixed by main and not changed here. Backup/restore capacity estimation, exact power-loss fault injection, and a full restore with a provisioned model remain separate qualification work.
