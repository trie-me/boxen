# Photo collection and token-limit repair — 2026-09-20

The user confirmed the previous Mac connection problem resolved. This work
addresses actual analysis failures and the clarified photo-collection workflow.

## Failure and repair

The user's crowded uploaded photo exhausted 2,048 output tokens twice. The two
failed runs took 52,017 ms and 50,326 ms. The worker repeated the same deterministic
request because truncation was classified as generic invalid output.

`inventory-v3` uses a compact generation contract: name, visible quantity,
confidence estimate and brief evidence per item, plus scene summary/warnings.
The adapter validates it and expands it into the unchanged canonical observation
contract. Bounding boxes and detailed attributes are null, not fabricated.
Runtime thinking is disabled for this extraction task. A truncated response gets
one retry at the provisioned ceiling, within one overall time budget: this
installation uses 2,048 initially and 4,096 at most. A second truncation fails
actionably without partial suggestions or another identical worker retry.

Prompt SHA-256: `8f0e89fe5b9215b9ba83967314cd993279ef94c14046114a345726df0de7696e`.
Generation-schema SHA-256: `041c5065ec089a8826709d439e35074ed16920d94b7950f8d1ca5a398c4e79c4`.
Canonical output schema, weights, projector, CPU runtime and licenses are unchanged.

## Actual local-model verification

Two opt-in tests passed against the running local llama.cpp/Qwen CPU runtime,
using a candidate profile and disposable databases/media. No private image or
model output was sent outside this host. Private photo content is not copied
into this record or the test artifact.

| Input | Model time | Output tokens | Result |
| --- | --- | --- | --- |
| Public coffee photograph, objects outside a box | 6,235 ms | 186 | 3 suggestions; anonymous review/accept/search passed |
| Exact user upload that previously failed | 10,591 ms | 416 | 8 pending suggestions, zero confirmed items, no truncation |

Both completed on the first request with finish reason `stop`. The larger-budget
recovery path is covered with deterministic adapter regressions; these photos
did not need it. Timings are observations, not latency guarantees. JUnit:
`artifacts/tests-real-ai-v3.xml` (2 passed in 18.68 seconds including test setup).

This verifies operational recognition, not exhaustive recognition or count
accuracy. Crowded/overlapping objects can be missed, and separate views can
repeat one item. Manual review remains required. YOLOE has not been integrated.

## Shared inventory behavior

The prompt and UI explicitly allow staged items, close-ups/reference views and
photos with or without the container. Analyze-all batches independent photo
jobs into a shared box review queue. `ImageView.latest_analysis` persists status
across navigation/devices, including successful empty results. Batch submission
skips already-active/successful jobs; failures can be retried individually.
Linking a second photo's suggestion to an existing item preserves its quantity.

See [ADR-0006](../system-design/adrs/0006-photo-collection-inventory.md).

## Regression and deployment

- 166 backend tests passed, with 52/52 successful API operations covered. The two
  opt-in real-model tests are skipped in the default run and passed separately.
- 44 frontend unit tests, 5 genuine LAN/insecure-context browser tests and 7 existing
  browser scenarios passed. The collective workflow includes cross-browser state,
  empty successful analyses, explicit reanalysis confirmation, queue/model errors,
  and two-photo evidence linking without duplicate counts. Mobile375px checks
  found no overflow or automated WCAG AA violations.
- Python/TypeScript checks, lint, formatting and production build passed.
- Native profile promoted to v3 after verification; web and worker restarted,
  inference process and all model binaries retained. No global tools or network
  settings changed. The live original photo was already marked deleted; the
  attempted retry stopped at404, preserving that deletion. No live suggestions
  or confirmed inventory were created by the retry.

Backend JUnit: `artifacts/tests-photo-collection.xml`; browser artifacts under
`frontend/test-results-lan/`. Container deployment was not rebuilt for this change.
