# Tags and collections: verification and deployment

Date: 2026-09-20. Independent local application. See [ADR-0008](../system-design/adrs/0008-tags-and-collections.md).

## Delivered

- Reusable box tags, normalized for uniqueness, editable as removable chips with existing-tag suggestions.
- Named, described collections with many-to-many box membership, rename/delete and itemized contents.
- Source-box or item-name grouping, item-name/source-box filters, quantities and units, and links to each original box.
- No copied inventory, implicit item merging or quantity summation. Unknown quantities stay unknown.
- Exact tag/collection filters on box lists and search; tag/collection names included in local FTS search.
- Explicit archived-content inclusion. Archived memberships remain visible and cannot be changed until restored.
- Anonymous editor support; viewer read-only; CSRF, ETag conflicts and idempotent retry protections retained.
- Mobile Collections entry from Your boxes; no additional crowded bottom-navigation target. No remote assets or inference changes.

## Automated and visual checks

- Full backend suite: **326 passed, 2 opt-in real-model tests skipped**, zero failures, **59/59 API operations** covered. Successful JSON responses are contract-validated. JUnit: `artifacts/tests-organization.xml`.
- **91 frontend unit tests** pass, including 27 new organization-helper cases. Covers tag handling, all-page membership loading, failed traversal, archived selection, filter preservation, distinct quantities and stable retries.
- **16 browser scenarios** pass: 9 LAN HTTP/anonymous-editor cases plus 7 baseline login/viewer/resilience/accessibility cases. The baseline configuration skips the 9 separately executed LAN scenarios, rather than counting them as passes twice.
- The new full browser flows create tags/collections/boxes, reuse canonical tags, filter/search, show mixed-unit and unknown-quantity items, preserve overlapping memberships, remove a membership, rename/delete a collection without deleting contents, and handle archived and stale edits.
- Phone editor and collection contents pass automated WCAG A/AA axe checks; no overflow at checked 320/375px widths. Desktop and mobile screenshots inspected. Screenshot evidence is under `frontend/test-results-lan/organization-*.png`.
- Browser requests stay local and no page errors occur. Tests use disposable inventory, not the user's live boxes.
- Python Ruff/format/mypy, TypeScript, Prettier and staged Vite build pass. Both OpenAPI copies and both 0002 SQL copies match.

Two test-harness issues were corrected: a tag region/input shared a label so the
selector now targets the textbox, and URL-driven checkbox changes require an
eventual checked-state assertion after React navigation. An existing Box PATCH
client remains compatible: idempotency keys are honored when supplied, not newly
required. New collection mutation endpoints require keys.

## Migration and recovery

0001 SQL and its Alembic revision remain checksum-identical. 0002 adds STRICT
relation tables and rebuilds expanded FTS atomically. Tests cover fresh/legacy
upgrades, corrupt/future/gapped histories, mismatched ledgers, runtime locks,
transactional rollback, exact source/search preservation, and old/current backup
verification and staged restore. Restore leaves original backup bytes and
manifests unchanged and preserves installation identity, session key and media.

The existing native installation was upgraded offline after stopping only its
web and worker services. Verified pre-upgrade backup:

`.local/boxen/data/backups/pre-organization-20260921T023214Z`

The backup's original source rows exactly matched the stopped database. After
official initialization to 0002, exact row comparisons passed for boxes,
inventory, images, analysis jobs/runs/observations, tombstones, users, sessions
and audit history; the session secret remained unchanged. Integrity and foreign
keys pass, search has zero mismatches, and organization tables start empty. No
live inventory was seeded or modified to demonstrate this feature.

Web and worker were recreated with their previous configuration, LAN bind,
working directory, restart policy and transient service lifetime. Web PID237430,
worker PID237431; AI PID125813 was untouched. Readiness and all three services
were healthy with zero restarts at verification. These services remain transient,
not boot-enabled.

The tested `.local/organization-build` assets were promoted with old hashed
chunks retained and `index.html` copied last. File comparisons match the staged
build. Published index SHA256:
`59adaf1adc1af03bac25b0ddc9e1582de91c57e6fb5840c58e118ba8dc7eff07`.
The actual LAN Collections screen renders with anonymous editing, a create form,
and the empty initial collection list.

## Limits

No capacity test, physical phone/printer qualification, new model accuracy claim,
container rebuild, WAN exposure, global installation or tool-manager change was
made. Collections are flat views, not nested containers. Existing camera HTTPS
requirements and independent-per-photo AI behavior are unchanged.
