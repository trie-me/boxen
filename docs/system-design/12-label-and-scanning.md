# Label and Scanning Specification

## 1. Canonical identity

- Display code: `BX-XXXX-XXXX` per the DDD `BoxCode` rules.
- Generated QR payload: UTF-8 bytes for `boxen:v1:<canonical-code>`, no BOM or trailing newline.
- Payload is host-independent and immutable for the box lifetime.
- QR parser accepts canonical payload, flexible typed code, and an exact configured local Boxen URL alias as input; generators emit canonical payload only.

## 2. QR symbol generation

- QR Code Model 2.
- Byte mode and the smallest version that fits the canonical payload.
- Error correction level Q by default; level H MAY be used when the selected physical profile preserves minimum module size.
- Quiet zone: at least four modules on every side, printed white/unmarked.
- Dark modules: solid near-black; light modules: white. Cyberpunk colors/glows/gradients are forbidden in printable QR marks.
- Target physical module size: at least 0.60 mm; absolute minimum after renderer/printer tolerance: 0.50 mm.
- Integer raster scaling only when generating raster previews; PDF uses vector modules aligned to the profile grid.
- No logo, icon, rounded module, decorative finder pattern, inverse color, or transparent background.

## 3. Built-in label profiles

### `roll-62x29-mm-v1` (default compact)

| Property | Value |
| --- | --- |
| Page | 62.0 × 29.0 mm, landscape |
| Safe margin | 2.0 mm |
| QR allocation | 25.0 × 25.0 mm at left |
| Text area | Remaining width, 2.0 mm gap |
| Name | Up to 2 lines; 12 pt nominal; 9 pt minimum |
| Code | 11 pt monospaced bold |
| Brand mark | Optional `BOXEN`, 6 pt |

### `sheet-4x2-in-v1` (large)

| Property | Value |
| --- | --- |
| Page | 101.6 × 50.8 mm, landscape |
| Safe margin | 3.0 mm |
| QR allocation | 40.0 × 40.0 mm at left |
| Text area | Remaining width, 4.0 mm gap |
| Name | Up to 2 lines; 20 pt nominal; 12 pt minimum |
| Code | 15 pt monospaced bold |
| Brand mark | Optional `BOXEN`, 8 pt |

### `sheet-a4-2x7-v1`

One A4 page containing 14 labels, each 99.1 × 38.1 mm in two columns/seven rows. Sheet margins/gaps are encoded in the profile fixture and verified against the selected stock. Each cell uses the same content constraints as the large profile with a 30 mm QR allocation.

Additional profiles require physical test evidence and a new profile version; user-created arbitrary profiles are deferred.

## 4. Typography and content

- Bundle and embed checksum-pinned Noto Sans and Noto Sans Mono subsets (SIL Open Font License notices included), or replace them only through an ADR and fixture update.
- Label background is white and ink is near-black for commodity thermal/laser printers.
- Name is trimmed and Unicode-normalized for rendering but stored source is unchanged.
- Name fits at nominal size, then decreases deterministically to minimum, then ellipsizes the final line. QR and code never shrink to make room.
- Current collection names, when present, print beneath the name in Noto Sans,
  alphabetically ordered and joined with a middle dot. Compact labels allocate
  one line at 7.5 pt; large/A4 labels allocate up to two lines at 9 pt, shrinking
  to 8 pt before ellipsizing. The title can shrink within its existing bounds
  to preserve separation. QR allocation, quiet zone and typeable code stay fixed.
- Memberships are read in the rendering transaction for individual, pinned and
  collection sheets; each box uses all its own current memberships. Ungrouped
  boxes have no collection line. Regenerate PDFs after membership/name changes.
- Canonical code appears exactly once in readable text and as part of QR payload.
- Inventory, description, user, location, timestamps, and network address are never printed in v1.
- Renderer includes no dynamic creation time so identical inputs produce identical content bytes aside from controlled PDF object metadata; deterministic tests normalize/omit that metadata.

## 5. PDF contract

- One exact-size page per roll label; exact A4 page for sheet profile.
- Physical units are converted deterministically to PDF points.
- Fonts embedded/subset; no printer font dependency.
- Vector QR modules; text remains vector glyphs.
- Metadata includes Boxen renderer/profile versions but no username or host path.
- Individual-label ETags derive from box code/name/version, full normalized
  collection names (including ellipsized text), profile key/version, font
  checksums and renderer version. Batch ETags include the PDF bytes and full
  per-box collection-name lists. Collection order is deterministic.
- Filename is sanitized `<box-name>-<box-code>.pdf` with bounded ASCII fallback.
- UI says `Print at 100% / Actual size` and detects/warns that browser print preview scaling cannot be controlled by Boxen.

## 6. Scan pipeline

### Live camera

1. User explicitly starts camera.
2. Browser requests `video: { facingMode: { ideal: "environment" } }`, no audio.
3. Decode frames entirely in browser at a bounded rate (target 10 fps maximum decode work).
4. On first parse-valid Boxen candidate, pause decoding and stop all media tracks.
5. Client validates payload syntax/version/code checksum.
6. Send original decoded input to `POST /codes/resolve`; server revalidates and resolves authorization/lifecycle.
7. Show brief resolved name/code confirmation, then navigate to box detail.

Repeated identical detections within two seconds are debounced. A different candidate after a failed resolution can be scanned immediately.

### QR image upload

- Accept local image via file picker/camera capture.
- Decode client-side from a downscaled working copy; neither original nor working image is sent/stored.
- Release object URLs/buffers after result or cancellation.
- If several QR codes exist, show only parse-valid Boxen candidates; when more than one remains, ask the user to choose by decoded code.

### Typed code

- Accept case-insensitive text with optional spaces/hyphens.
- Normalize visually after complete groups or blur; do not disrupt caret mid-edit.
- Client gives immediate syntax/checksum feedback.
- Server always re-parses and decides existence/lifecycle.

## 7. Scanner states

| State | UI response |
| --- | --- |
| Camera permission not requested | Explain purpose; `Start camera` button |
| Permission denied | Plain guidance plus Upload/Type tabs |
| No camera / insecure context | Explain local HTTPS/device setup; alternatives remain |
| Searching | Live preview, static reticle, Stop button |
| Decode timeout (20 s) | Keep preview; suggest distance/light/upload; Retry |
| Non-Boxen QR | `This code is not a Boxen label`; continue scanning |
| Unsupported `boxen` version | Show version and update/admin guidance; never guess |
| Invalid code checksum | Show exact invalid code and retry/type action |
| Unknown valid code | `No box uses this code` with search/create only when authorized |
| Archived box | Show name/code and `Archived`; owner/editor restore action |
| Success | Stop camera, announce name/code, navigate once |

## 8. Security and privacy

- Camera/video and uploaded QR images stay in the browser.
- No frame/decoded non-Boxen value is logged.
- Decoded content is never navigated as a URL or inserted as HTML.
- Maximum decoded text length 512 Unicode scalar values.
- Decoder worker/library is bundled and checksum-pinned.
- Permission is requested only on explicit action and all tracks stop on hidden page, route change, success, cancellation, logout, or error.

## 9. Verification

- Code/payload parser property and fuzz tests.
- QR round-trip from generated SVG/raster/PDF for every profile.
- Programmatic page size, quiet zone, module geometry, code text, long-name behavior, font embedding.
- Real printer at actual size and target-phone matrix under varied light, angle, distance, and minor damage.
- Live camera permission accepted/denied/revoked; no-camera/insecure-context/upload/type alternatives.
- Assert zero camera tracks after every terminal/route state.
- Assert QR upload bytes never appear in network requests or persistent browser storage.



## 10. Batch printing and pin lists (2026-10-02)

`/print-list` holds ordered unique box codes in browser storage, scoped by the
current user ID. Selection is available on box cards, search results, box detail
and the single-label screen. Pins survive navigation/reload, and the header
shows their count. This is a browser convenience, not new inventory or a
server-synchronized collection. Collection printing uses
`/collections/:collectionId/labels` and leaves the pin list untouched.

`POST /api/v1/labels.pdf` takes exactly one of `box_codes` (1–500 unique codes,
ordered) or `collection_id` (current members in name/code order, including
archived members). It resolves names and membership when generating the PDF.
Missing boxes/collections and empty or oversized sets fail as a whole; no labels
are silently omitted. Editor/owner authorization, same-origin and CSRF checks
apply. The existing label limiter is shared: 30 documents per actor per minute.
Generation changes no inventory, memberships or audit/idempotency records;
PDF bytes are not stored in JSON retry records. No database migration is needed.

The fixed batch profile is US Letter (612 × 792 PDF points), two columns and five
rows of 4 × 2-inch labels, 0.5-inch top/bottom margins, 0.15625-inch side margins,
and 0.1875-inch horizontal gutter. Labels fill left to right, top to bottom,
continuing on as many pages as needed without a trailing blank page.
`start_position` (1–10) skips slots only on the first page. `offset_x_mm` and
`offset_y_mm` (−3 to +3, positive right/down) translate all labels without scaling.

The geometry targets [Avery 5163/8163 stock](https://www.avery.com/templates/5163),
with margin/pitch values cross-checked against the
[LibreOffice label database](https://github.com/LibreOffice/core/blob/master/extras/source/labels/labels.xml)
(Avery Letter Size 5163). Inch fractions are used directly instead of the
rounded hundredths-of-a-millimeter values in that database. The PDF requests
`PrintScaling=None` and `Duplex=Simplex`; the UI still instructs users to select
Letter, actual size and portrait, and to check a plain-paper test against stock.
Physical printer qualification is separate.

Batch previews receive the already downloaded PDF bytes directly, preserving
the existing Content Security Policy. The same PDF blob supports opening and
downloading. Preview page navigation includes every generated page. Changing
selection, label versions or alignment invalidates the previous PDF. Blob URLs
are revoked and outstanding downloads aborted when the builder unmounts.
