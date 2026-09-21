# ADR-0005: Small local deployment and anonymous access

Status: accepted scope correction, 2026-09-20. User clarified that Boxen is normally a single-user or low-user local application, with anonymous access, and does not need capacity testing.

## Changes to the original baseline

- Large-dataset/concurrency benchmarks are **not a build or release gate**. The original capacity targets and benchmark work packages are superseded for this project. Ordinary functional, recovery, security, and responsive-UI tests remain.
- Inventory browsing, search, and scan lookup must work without an account when anonymous access is enabled. Account-required access is no longer the default UX.
- `BOXEN_ANONYMOUS_ACCESS` selects `viewer`, `editor`, or `off`. The default is **`editor`**, following the owner's explicit correction that a local inventory app must allow adding boxes without account setup. `viewer` is an opt-in read-only mode; `off` restores account-required access.
- System administration, backup management, user management, and irreversible purge remain owner-only. Anonymous access does not expose administrator privileges or bypass backup/purge safeguards.

## Security and data model

Anonymous browsers receive local session cookies and individual CSRF tokens. There is no personal registration requirement. A protected internal anonymous principal supports existing relational provenance; anonymous changes are not attributable to a particular person. The mode is host configuration, never client-selected. Same-origin, exact-host, ETag, validation, upload limits, and HTML sanitization still apply.

Anonymous access grants the selected permissions to **anyone who can reach the configured host**. Explicit native LAN binds are supported in development mode over HTTP, with an exact origin derived from a concrete bind address when replacing the old loopback origin. Wildcard binds require a concrete browser origin. Host/Origin/CSRF checks are not disabled. HTTP is permitted for ordinary trusted-LAN inventory and uploaded/typed QR use, not for public exposure. Production retains HTTPS; trusted TLS is required for live phone-camera APIs and encrypted traffic. This supersedes the original loopback-only development restriction.

The setup token and first-owner flow remain available for administration and editing when anonymous mode is view-only. An anonymous visit must not consume or close first-owner setup. Local AI remains optional and human-reviewed.

## Verification

Cover account-free opening, browsing/search/scanning, viewer mutation denial, configured anonymous editing, per-browser CSRF enforcement, administrator denial, protected anonymous identity, and first-owner setup after an anonymous visit. Do not introduce a high-concurrency benchmark as a substitute for these everyday-use checks.
