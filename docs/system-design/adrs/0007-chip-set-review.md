# ADR-0007: Review a proposed inventory as an editable chip set

Status: accepted user request, 2026-09-20.

The main AI review interface is a list of item-name chips. Each has an accessible
remove button. An adjacent text field and Add button add missing items. One
Accept items action commits the edited set. Tapping a chip opens optional detail
editing, including quantity, source evidence and explicit linking to a confirmed
item; those details do not dominate the default view.

Removing an AI chip only changes the local draft until acceptance, at which point
its pending observation is rejected. Removing a manually added chip discards that
draft addition. Neither operation removes existing confirmed inventory. Accepting
an empty visible set is meaningful when all its AI suggestions were removed.
Manual-only sets are also supported.

Detected quantities and source observation links survive the compact UI. Missing
quantities remain unknown, not an invented count of one. Separate observations
with identical names remain separate until the user removes one or explicitly
links it to a confirmed item. A name match alone is not identity proof. Linking
photo evidence does not add the observed quantity again.

`POST /boxes/{box_code}/observations/review` is an additive API with `accept`,
`reject` and `add` arrays. The transaction validates all submitted observations,
the active box, and any existing-item version preconditions before committing.
Any failure rolls back the entire set. Normal editor authorization (including
anonymous editor), CSRF, audit and idempotency rules apply. Suggestions arriving
after the submitted snapshot remain pending. The existing individual-decision
API remains available for compatibility.

The UI keeps polling from overwriting draft removals, edits or additions. It
loads the pending pages, deduplicates by observation ID, and explicitly bounds
each submitted set to 500 actions. This is a payload safety bound, not a capacity
target. A lost response retains a frozen payload and retry key; editing stays
locked until that same request is resolved so retrying cannot add items twice.
Successful saves refresh inventory/search/review state.

Verification includes mixed accept/remove/add, removing all chips, manual-only
addition, explicit evidence linking, late suggestions, stale-version rollback,
cross-box denial, and lost-response replay. Mobile layout, keyboard controls,
accessible remove names and local-only requests are checked in the browser.
