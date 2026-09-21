# ADR-0008: Organize boxes with tags and collections

Status: accepted implementation of user request, 2026-09-20.

## Product model

A tag is a reusable label such as `fragile`, `camping`, or `cables`. A collection
is a named set of related boxes, such as `Office move` or `Workshop supplies`,
with a description and a combined itemized view. A box can have multiple tags
and belong to multiple collections. Collections are flat, not nested boxes.

Tags and collection names are trimmed, Unicode-normalized and case-folded for
uniqueness. Display spelling is retained. Reusing an existing tag reuses its
identity; it does not create a case-only duplicate. Tags can be added/removed in
the box editor. Collections can be created, renamed, described and populated
from either the box editor or collection membership editor.

Collections are views over existing inventory, never copies of boxes or items.
The itemized view includes each item's box name and typeable code, quantity and
unit, with links back to the source box. Unknown quantities stay unknown. Equal
item names are not automatically merged and incompatible units are not summed.
Removing a box from a collection or deleting a collection leaves the box, its
photos and inventory intact. Tags and memberships do not change QR identities
or the printed-label content.

## Read and write behavior

Box lists and inventory search support exact tag and collection filters, joined
with AND when both are selected. Search also indexes tag and collection names.
Pagination cursors bind to those filters. Collection itemization excludes
archived boxes by default, with an explicit option to include them. Membership
responses always identify archived members so an editor never silently removes
them by saving a filtered view. Archived membership cannot be changed until the
box is restored. Removed inventory items and unaccepted AI observations are not
included in itemization.

Normal editor permissions include the configured anonymous editor; viewers can
browse but cannot mutate. Existing CSRF, idempotency and ETag checks apply. A
membership change updates both collection and affected box versions, and changes
to indexed organization names rebuild affected search projections. Omitted patch
fields preserve their values; an explicit empty list clears a relation. Relation
and search updates commit in the same SQLite transaction.

## Storage and migration

Migration 0002 adds `tags`, `box_tags`, `collections`, and `collection_boxes` with
foreign keys, uniqueness constraints and reverse lookup indexes. The FTS5
projection gains tag/collection text and is rebuilt from existing source rows.
The checksum-pinned 0001 source is immutable. Startup never silently upgrades a
database; an explicit offline migration checks the known historical prefix.
An existing-data backup and migration/restore rehearsal precede live migration.
Existing 0001 backups remain verifiable and can be upgraded in a staged restore.

## UI and verification

Use tag chips, a collection selector and linked badges consistent with the local
cyberpunk UI. Collections have a list, create/edit controls and a searchable
itemized view grouped by box. Keep mobile navigation readable; collections must
be discoverable from Boxes without squeezing another bottom-navigation target.

Checks cover normalization, overlapping membership, filters/search, source box
identity, unknown and distinct-unit quantities, empty/archived groups, relation
deletion without inventory loss, role/CSRF boundaries, stale writes, atomic
rollback, migration preservation, old/new backup compatibility, offline assets,
mobile layout and accessibility. High-user-count/capacity tests remain out of
scope for this small local application.
