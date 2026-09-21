# ADR-0009: Contextual, local search suggestions

Status: accepted implementation of user request, 2026-09-20.

## Intent and thresholds

Typeahead is a small typed discovery read model, not a replacement for submitted
full-text search and not an AI inference request. An explicit box-code prefix
selects box lookup; ordinary text selects contents and organization labels.

- No suggestions or requests for empty text or fewer than two Unicode letters
  or numbers. Two-character non-Latin names are eligible too.
- `BX` and `BX-` reserve box-code intent. At least two valid payload characters
  after `BX-` are required, for example `BX-7K`. Code comparison ignores case
  and accepts the existing `O → 0`, `I/L → 1` aliases. An optional separator
  after four payload characters is accepted. Invalid reserved prefixes never
  fall through to unrelated item suggestions.
- A meaningful code prefix suggests boxes only, with both name and full code.
- Other text suggests confirmed item names, tags and collections. Item matches
  identify their containing box. Box names and descriptions are still included
  when the user submits ordinary Search; they do not populate text typeahead.

## Application boundary and contract

The Discovery module exposes `GET /api/v1/search/suggestions`, operation
`suggestSearch`, under the same read permissions as full search. Parameters are
`q`, `include_archived`, optional `tag_id`, optional `collection_id`, and `limit`
(default8, maximum12). The response contains normalized `query`, classified
`kind` (`none`, `box_code`, `text`) and a bounded `suggestions` list. Every row
contains `kind`, `id`, `label`, `detail`, and nullable `box_code`. Suggestions
carry existing entity identities; they do not create new domain entities.

Use only local SQLite data. Every candidate respects the current tag/collection
filters and archive visibility; deleted items, pending AI observations and
organization labels with no visible box membership are excluded. Equal item
names in different boxes remain separate. Query text is data, not SQL/FTS syntax.
Ordering is deterministic and multiple entity types remain discoverable under
the bounded response. No schema migration, model download or remote dependency
is needed. The two OpenAPI contracts and generated client types remain aligned.

## Interaction

All shared search bars use the same editable combobox. Suggestions are manual,
not automatic selection: Enter normally submits the original full search.
Arrow keys select a result; Enter opens it. Escape dismisses without changing
the query; Tab moves normally without selecting. Mouse/touch selection opens
the box, the named collection, or the tag-filtered box list. Item selection opens
the containing box rather than guessing which duplicate inventory line to merge.

Keep focus in the input, expose the active option with `aria-activedescendant`,
announce result status, and provide visible entity-type labels and touch-sized
rows. Follow the [WAI-ARIA editable combobox pattern](https://www.w3.org/WAI/ARIA/apg/patterns/combobox/).
Do not intercept normal text editing or submit during IME composition.

Debounce eligible input250ms. Abort on query/filter/focus changes, ignore stale
responses, and bound a suggestion request to5seconds. A failed or empty lookup
never disables normal Search. No saved query history or analytics are introduced.

## Verification boundary

Cover prefix thresholds and aliases, Unicode, matching and ordering, response
limits, lifecycle and permission filtering, local-only requests, duplicate names,
keyboard/manual submit, touch selection, IME composition, stale responses,
timeouts, mobile overflow and accessibility. Use disposable data. This does not
qualify a physical Motorola device or change the still-HTTP camera deployment.
