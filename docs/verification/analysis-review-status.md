# Analysis review status

Date: 2026-09-20. Frontend-only correction for the independent local app.

## Behavior

Successful analysis previously always said to review suggestions, even after
every chip was accepted or removed. Photo cards now read the pending observations
from the same query as the shared review editor:

- Pending suggestions: show this photo's remaining count and the review prompt.
- None pending: show “Complete. No suggestions left to review.” This also covers
  successful photos with no detections.
- Loading: show “Complete.” without claiming review is finished.
- Failed status read: show “Complete. Review status unavailable.” rather than
  interpreting missing data or cached counts as a completed review.

Counts include unresolved observations across a photo's analysis runs; another
photo's pending suggestions do not keep a processed photo's prompt alive.
The shared query loads all pages, deduplicates observation IDs and ignores
settled decisions. Successful mutations invalidate it; five-second foreground
polling and refetch-on-focus discover reviews completed in another browser.
Analysis success remains distinct from a user's review decision. No suggestions
are automatically accepted, removed or merged by this change.

## Verification

- All 174 frontend unit tests pass, including ten additional status/count cases.
- TypeScript, formatting and staged production build pass.
- All nine LAN/organization browser scenarios and seven baseline browser
  scenarios pass against disposable databases and the staged frontend. The
  baseline configuration intentionally skips 32 separately configured scenarios;
  those are not counted as passes. Unrelated dedicated scanner, authentication
  and typeahead suites were not rerun for this frontend-only change.
- The expanded collective-photo test exercises accepted and rejected chips,
  zero detections, newly added photos alongside reviewed photos, explicit
  reanalysis, another browser rejecting the final chip, an open page updating
  without reload, failed pending-status reads, recovery and a final reload.
- Existing mobile-width overflow and review-screen automated accessibility
  checks pass. The 375px collective-photo screenshot was visually inspected:
  `frontend/test-results-lan/collective-photos-phone.png`.

Reproduce the relevant browser suite after building a staged candidate:

```sh
pnpm --dir frontend test
pnpm --dir frontend build --outDir ../.local/analysis-review-status-build
BOXEN_TEST_FRONTEND_DIR=/path/to/boxen/.local/analysis-review-status-build \
  CHROME_BIN=/usr/lib64/chromium-browser/chromium-browser \
  pnpm --dir frontend exec playwright test --config playwright.lan.config.ts
```

No backend, schema, AI runtime, account, camera, HTTPS or network configuration
changes are part of this fix. Physical Motorola verification is not claimed.

## Deployment

The tested `index-B_lWURZe.js` frontend is deployed at
`http://192.0.2.10:8000`. Old hashed assets were retained and the entry point
was copied last; rollback entry point:
`.local/analysis-review-status-previous-index.html`. The served index and new
JavaScript match the staged build byte for byte.

At 20:35 PDT, a read-only 375px browser check confirmed the new per-photo status
on existing data, no unconditional review prompt, no horizontal overflow, no
page errors and no external requests. No inventory mutation or analysis was
performed. Readiness remains healthy; web312981, worker237431 and AI125813 all
remain active, unchanged, with zero automatic restarts.
