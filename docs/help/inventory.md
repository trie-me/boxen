# Use your inventory

## Boxes, contents and organization

Create a box with a short name and optional Markdown description. Add inventory items with a name, optional quantity and unit. Unknown quantity remains unknown. Tags provide reusable labels; Collections group existing boxes without copying their contents. Removing a collection membership leaves the original box and inventory intact.

Search by box code, item, name, description, tag or collection. Suggestions appear after two characters and respect the selected filters. Select a suggestion, or press Enter to search normally. Your boxes and Search both support tag and collection filters.

Archive boxes when they are no longer in daily use. Restore them when needed. Permanent purge is a separate owner action and requires recent sign-in; backups are the recovery path after deletion.

## Photographs and optional AI

Attach photos of packed contents, items laid out beside a box, close-ups or reference views. Photos collectively document that box. **Analyze all photos** runs separate analyses and gathers suggestions into a shared review. The model does not jointly recognize duplicates across photos.

New JPEG, PNG and WebP uploads are saved as **WebP at quality 85, with a maximum longest edge of 2,048 pixels**. Boxen preserves proportions and transparency, applies camera orientation, removes embedded metadata, and never enlarges smaller photos. The full-size view uses this optimized file; a 480-pixel thumbnail keeps browsing light. The uncompressed or larger source upload is not retained, so keep your own source copy if you need it. Existing photos are unchanged.

Box cards, search results and photo grids load the small thumbnails as they approach the screen. Opening a box does not download every full-size photo. Select a photo to open its larger view; AI review also uses thumbnails for its source preview. Thumbnails can be rebuilt from saved images during recovery without changing the originals.

Review each suggestion, remove unwanted chips, add missing items, edit quantities and accept the final set. Link repeated views to an existing item to avoid double counting. Suggestions do not become inventory until reviewed. **Analyze again** creates new suggestions and asks for confirmation. Model output may be incomplete or wrong; manual editing always remains available.

[Local AI](/help/models) explains installation and [Remote AI](/help/remote-ai) explains deliberate use of an external endpoint and what leaves the host.

## Labels and scanning

Use **Pin label for printing** on boxes, search results or details, then open **Print list**. Pins are stored in this browser for the current account. **Print collection labels** includes all collection members, including archived boxes, without changing the pins.

Batch PDFs use US Letter, a 2 × 5 grid of 4 × 2-inch labels (Avery 5163/8163), up to 500 labels. Choose the starting position for partially used sheets and adjust alignment. Print portrait, single-sided, **100% / actual size**. Test on plain paper against your stock before printing labels; physical printer alignment is device-specific.

Every label includes the box's current collection names beneath its name when it belongs to a collection. Multiple names are sorted alphabetically and separated by a middle dot. Compact labels allow one collection line; larger labels allow two. Long names or lists end with an ellipsis so the QR and typeable code stay readable. Generate a new PDF after renaming a collection or changing membership; already downloaded or printed labels are static.

Scan a label using live camera, **Take QR photo**, uploaded QR image or the typed code. Camera access requires browser permission and a secure context. The photo picker depends on the phone/browser. Uploaded QR images are decoded locally, without an external decoding service.

## Save and recover

Changes save to the host, not to a cloud inventory account. Keep the host reachable while editing. If another person changed the same record, reload and reconcile the newer version rather than overwriting it. If your session expires, sign in again and retry. Use [Backups and recovery](/help/recovery) for data protection.
