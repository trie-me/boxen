# Batch label printing

Implemented and tested in source on 2026-10-02; deployed to the existing native
HTTPS installation on 2026-10-03 after the user reported the controls missing.
The tested `.local/label-print-build` assets were promoted with the index switched
last. Only `boxen-web.service` was restarted; worker, proxy and AI processes
remained unchanged. No schema, inventory or configuration changes.

## Behavior

- Ordered, unique browser pin list, scoped by account, up to 500 boxes. Checkboxes
  on home/box cards, search results, detail and single-label pages. Header count,
  add all loaded boxes, remove individual pins and clear list.
- Collections can be printed directly, including archived members, using current
  server membership and names in name/code order. Printing does not edit pins or
  collection membership.
- One Letter PDF, ten 4 × 2-inch labels per page. Additional pages are automatic.
  First position 1–10 supports partly used sheets; X/Y offsets support ±3 mm
  calibration. Preview every page, open to print or download the same PDF.
- Explicit stock, paper size, actual-size/100% and single-sided instructions.
  [Avery's template](https://www.avery.com/templates/5163) identifies the stock;
  [LibreOffice's label database](https://github.com/LibreOffice/core/blob/master/extras/source/labels/labels.xml)
  was used to cross-check side margins and pitch. No physical stock/printer test.
- Empty collections, deleted pins, invalid settings, permissions and failed
  requests are handled without partial printing or loss of the list. Retry
  generates from current server state. New `/labels.pdf` POST enforces editor
  permission, Origin/CSRF, bounded input and existing label rate limiting.

## Verification

682 backend tests pass (two opt-in real-model tests skipped), covering 61/61 API operations. All 184 frontend units, three new printing browser cases, nine existing LAN/organization cases and seven signed-in/viewer/session-recovery cases pass (19 browser scenarios total). Ruff, mypy, TypeScript, Prettier, OpenAPI validation and the staged production build pass.

`backend/tests/test_label_sheet.py` checks Letter media boxes, row-major order,
page boundaries, blank first slots, a 500-label/51-page case, embedded fonts and
text bounds, long names, alignment offsets, deterministic bytes/ETags, current
names, collection membership and archived inclusion. Every QR on an 11-label
PDF decodes after Poppler rendering at 150 dpi. API checks cover source
validation, duplicate rejection, no business-data mutation, deleted/empty sets,
permissions, CSRF/Origin, anonymous editing, and rate limits.

`frontend/src/print-list-helpers.test.ts` checks storage corruption recovery,
ordered deduplication, capacity and partly used sheet counts.
`frontend/e2e/label-printing.spec.ts` exercises the actual API and generated PDFs
at 1280px and 375px: pin selection, reload persistence, removal, collection
printing, PDF page navigation and download, invalidation after setup changes,
empty collections and retry after an HTTP failure. Both viewport accessibility
checks pass WCAG 2 A/AA and 2.1 AA with no horizontal overflow.

Visual review: inspected both pages of an 11-label PDF, including a long name,
plus desktop/mobile print-list screenshots. PDF labels stay within their cells;
no clipped text, overlapped QR content or trailing blank page. Scratch renders
were reviewed in `tmp/pdfs/` and removed; browser screenshots are in ignored
`frontend/test-results-labels/`.

Reproduce against an isolated staged frontend rather than overwriting the live
static directory:

```sh
pnpm --dir frontend check
pnpm --dir frontend test
pnpm --dir frontend exec vite build --outDir ../.local/label-print-build
.venv/bin/pytest backend/tests
BOXEN_TEST_FRONTEND_DIR="$PWD/.local/label-print-build" \
  pnpm --dir frontend exec playwright test --config playwright.labels.config.ts
```

Set `CHROME_BIN` to a local Chromium binary if Playwright's browser is not
installed. Test fixtures own temporary data directories and terminate their
servers after the run. Existing individual roll, 4 × 2-inch and A4 profiles keep
their original behavior. Browser pin lists do not synchronize between devices.


## Live deployment verification (2026-10-03)

- HTTPS readiness passed before and after deployment with the existing CA.
- Verified an isolated browser at 375px and 1280px: pin two existing boxes,
  navigate to the print list, reload with pins retained, prepare the PDF, render
  its preview and download the real PDF. No page errors or horizontal overflow.
- The live collection detail exposes **Print collection labels** and opens the
  collection print page. A direct HTTPS batch request produced a valid Letter
  PDF containing both selected box codes.
- Browser verification allowed only reads and the PDF-render POST; no live
  inventory, membership or account edits. Ten inventory/account/audit table
  digests and the configuration file matched their pre-deployment values.
- Web process PID changed from 326235 to 685261. Worker 326237, proxy 326239 and
  AI 125813 remained active with no restarts.
- The previous frontend index and an integrity-checked SQLite backup are kept
  privately in `.local/label-print-deployment/2026-10-03/`. Old hashed assets are
  retained for tabs that were already open. No container cutover or image push.

Existing tabs must refresh to load the feature. On **Your boxes**, use
**Pin label for printing** under each box or **Pin all loaded boxes**. The
header's **Print list (N)** opens the saved selections.
