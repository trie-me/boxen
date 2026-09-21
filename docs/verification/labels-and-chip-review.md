# Box names on labels and editable chip review

Date: 2026-09-20. Independent local application, existing deployment/data preserved.

## Label verification

The existing PDF renderer already prints the box name above the typeable code,
beside the QR. No missing-name defect was reproduced, so the renderer was not
changed to claim a redundant fix. Visual checks covered all three profiles
(compact roll, 4 × 2 inch and fourteen-label A4 sheet), the browser canvas preview,
and a long-name compact/large pair. The compact profile wraps then ellipsizes
long names; the QR and code retain their size.

- `backend/tests/test_label_layout.py`: 29 passing checks for name/code presence
  in every cell, physical dimensions, embedded fonts, bounds and separation,
  normalized text, deterministic bytes, and ETags after renaming.
- The LAN Chromium workflow checks name-region pixels (not only canvas size),
  downloads the PDF and extracts the current renamed box name and code. Passed.
- The existing PDF-to-203-DPI QR decode regression remains applicable.
- No physical printer or label-stock qualification is claimed.

## Chip-set review

See [ADR-0007](../system-design/adrs/0007-chip-set-review.md) for the user flow,
atomic acceptance semantics and retry contract. The local vision model itself is
unchanged by this UI update; this verification does not make new recognition
accuracy or timing claims.

- Atomic-review API: 43 focused tests pass, including same-key concurrent replay,
  stale/cross-box rejection, source/quantity preservation, and transaction rollback
  covering search, audit and idempotency state.
- Full backend regression: **239 passed, 2 opt-in real-model tests skipped**, with
  **53/53 API operations** successfully exercised. The skipped tests are the real
  inference tests already run for the prior AI repair, not failures of this UI
  change. Reports: `artifacts/tests-review-set.xml` and
  `artifacts/tests-chip-review.xml`.
- Python lint, formatting and type checks pass.

- Frontend: **64 unit tests pass**, including 20 chip-draft checks. TypeScript,
  Prettier and the staged production build pass.
- Browser: **7 LAN + 7 baseline scenarios pass**. The LAN suite covers chip
  removal/addition before save, polling without resurrecting removals, atomic
  acceptance, reject-all, manual-only additions using a phone viewport, explicit
  evidence linking with unchanged quantity, and a committed save whose response
  is deliberately dropped then retried with the same payload/key.
- Review at 375 px has no horizontal overflow and no automated WCAG AA violations
  in Axe. The rendered chip screenshot was visually inspected. This does not
  replace a physical-device or screen-reader qualification.

## Additional QR regression found during label verification

A fixed synthetic QR payload (`boxen:v1:BX-SXSB-3DDA`) reproducibly defeated the
general photographic finder in the bundled decoder even though it was valid.
The pure-symbol decoder succeeds. QR uploads now try that local fallback only
after the normal decoder fails; camera frames keep their existing path. A fixed
browser regression checks decoded content reaches the normal server resolver.
No dependency download, remote service, payload/checksum change or camera
permission change was introduced.

## Deployment

The UI was built to `.local/chip-review-build` and both browser fixtures were
pointed there with `BOXEN_TEST_FRONTEND_DIR`, keeping unverified assets away from
the live app. After checks passed, only `boxen-web.service` was restarted (PID
186261). The exact staged assets were promoted, with old hashed assets retained
and the HTML entry point copied last. Worker150746 and inference125813 remained
running. The live LAN API verifies byte-identical frontend assets, anonymous
editor access and database/worker/AI/search all ready. Existing user inventory
and observations were not accepted, rejected, added or removed by deployment.
