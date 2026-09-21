# Contextual search typeahead

Date: 2026-09-20. Independent local application.

## Delivered behavior and design

The search bar classifies an eligible typed query without local or remote AI.
An explicit `BX-` plus two valid payload characters requests box-code matches.
Incomplete or malformed reserved prefixes do not trigger unrelated text
suggestions. Other text with at least two Unicode letters/numbers suggests
confirmed inventory item names, tags and collections, not box titles.
Submitting ordinary Search still searches titles, descriptions and contents.

Every option identifies its entity type. Item options include the source box;
selecting one opens that box. Tag selection opens a filtered box list and
collection selection opens its itemized view. Code selection opens the box.
Current archive visibility and tag/collection filters constrain suggestions.
Unaccepted AI observations, removed items and labels with no visible membership
are not candidates. Equal item names retain separate source-box identities.

The read-only endpoint uses local source tables and no schema change. Code
lookups bind an ASCII prefix. Text queries stream visible source rows, tokenize
Unicode names, keep only bounded top matches per entity type, then interleave
types deterministically. This is intentionally a small-app implementation, not
a new search service or a high-capacity benchmark claim.

## Interface checks

The editable combobox provides manual selection, arrow keys, Enter, Escape and
normal Tab/text editing. Input focus and active-option accessibility attributes
are separate; no option is chosen merely because it is listed. IME composition
does not prematurely search. Requests are debounced250ms, aborted on changed
input/filter/focus and limited to5seconds. Late responses cannot replace the
current query's results. Empty or failed suggestions leave full Search usable.

The implementation contract and intent details are in
[ADR-0009](../system-design/adrs/0009-contextual-search-suggestions.md).
The keyboard model follows the
[WAI-ARIA combobox pattern](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/).

## Repeat dedicated checks

Use disposable fixtures, not the live inventory:

```sh
.venv/bin/pytest backend/tests/test_search_suggestions.py
pnpm --dir frontend test
BOXEN_TEST_FRONTEND_DIR=/path/to/boxen/.local/search-suggestions-build \
  CHROME_BIN=/usr/lib64/chromium-browser/chromium-browser \
  pnpm --dir frontend exec playwright test --config playwright.suggestions.config.ts
```

Phone-sized Chromium with touch emulation verifies the interface, not a physical
Motorola or another browser engine. No camera/HTTPS configuration changes are
part of this search enhancement.

## Verification results

- Full backend regression:476 passed,2 opt-in real-AI cases skipped;60/60 API
  operations have successful response-contract coverage. JUnit:
  `artifacts/tests-search-suggestions.xml`.
- Frontend unit tests:164 passed, including32 intent/filter/navigation cases.
- A separate cross-language comparison verified matching frontend/backend
  classification for268 synthetic boundary queries. This is correctness
  verification, not capacity testing.
- Python lint/format/type checks, TypeScript, frontend formatting/build and
  equality of both OpenAPI YAML files passed.
- Dedicated typeahead browser suite:8/8 scenarios passed on the final
  `index-DpYT3CCo.js` candidate, with no page errors or non-local requests.
  Tests cover request thresholds, manual and selected Enter, arrows/Escape/Tab,
  post-navigation input, scoped page/global search, Unicode IME, debounce,
  cancellation, stale responses even when a transport ignores abort, failure
  recovery and the exact5second deadline.
- Actual touch events in emulated375px and320px contexts selected both items and
  collections successfully. Desktop and both phone-size popups passed automated
  WCAG A/AA checks and horizontal-overflow checks; all three screenshots were
  visually inspected. Artifacts: `frontend/test-results-suggestions/`.
- Final existing-feature browser regressions:1 auth,7 baseline,14 scanner and9
  LAN/organization scenarios passed. Together with8 suggestion scenarios, this
  is39 distinct passing scenarios. Baseline configuration skips dedicated suites,
  which are run separately; those skips are not counted as passes.

Initial browser failures were traced to assertions made before a route finished
rendering and to scanner tests selecting both the scanner's status and the newly
added search status. Tests now wait for the destination UI and scope scanner
status to the scanner's main region. Final runs passed without disabling tests
or relaxing the expected behavior. Route-scoped focus also prevents a delayed
navigation effect from closing freshly opened suggestions.

Backend tests include code normalization, text token-prefix matching, Unicode,
all filter/archive combinations, viewer/anonymous/disabled-user boundaries,
pending/rejected/accepted AI state, deletion and live membership changes,
deterministic type balancing, duplicates, response bounds and literal SQL/FTS
metacharacters. Suggestions do not depend on a healthy full-text projection.

## Local deployment

Deployed to the existing LAN app at `http://192.0.2.10:8000` on2026-09-20.
The staged `index-DpYT3CCo.js` build was promoted with old hashed assets retained
and the index copied last. All copied files matched the tested stage byte for
byte. Previous index: `.local/search-suggestions-previous-index.html`.

At20:22 PDT, read-only mobile-sized Chromium confirmed suppressed short `BX-`
input, code-only suggestions matching an existing box, ordinary text classified
without box suggestions, healthy readiness, no horizontal overflow, no page
errors and no external requests. Private labels/results were not recorded in
verification output. No inventory or account changes were performed.

Only `boxen-web.service` restarted (PID312981). Worker237431 and inference125813
were unchanged; all services remained active with zero automatic restarts at
verification. No database migration, networking change or global installation
was performed. Services remain transient rather than boot-enabled; this update
does not configure trusted HTTPS for continuous phone-camera scanning.
