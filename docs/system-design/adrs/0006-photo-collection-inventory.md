# ADR-0006: Photos collectively represent a box's contents

Status: accepted user clarification, 2026-09-20.

A box is an inventory grouping, not an image-recognition constraint. Its photos
may show packed contents, staged items, close-ups or reference views. Neither the
physical container nor the item's current storage location needs to be visible.
Do not infer actual containment or ownership from an image.

All associated photos contribute suggestions to one box-level review and
inventory. The current local model processes each photo independently; batch
analysis is not joint multi-image inference. Jobs and observations retain their
source image and run provenance. A durable `latest_analysis` on each ImageView
allows all clients to show progress and avoid repeating active/successful jobs,
including successful jobs with no detected items.

Overlapping photos must not silently inflate stock counts. Review explicitly
creates a distinct inventory item or links another view to an existing item
without adding quantity. Exact-name matches may prompt this choice but cannot
prove two views show the same physical object. No automatic acceptance,
cross-photo identity inference, or completeness guarantee is introduced.

For the CPU vision path, a compact internal generation schema supplies names,
visible quantities, confidence estimates and brief evidence. The adapter expands
this into the existing validated observation contract, leaving geometry and
unrequested attributes null. Its schema is included in the pinned prompt hash.
One larger-budget retry is allowed on truncation within the same time budget;
partial JSON is never converted into partial inventory. Exhausted truncation
does not trigger another identical worker retry. Token usage and attempt budgets
are recorded for diagnosis.

Verification: staged-photo recognition, a crowded-image regression, durable
per-photo state, batch retry/progress, and explicit two-photo linking with an
unchanged confirmed quantity. Capacity testing remains out of scope.
