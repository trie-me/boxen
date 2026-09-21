# UI/UX Specification

## 1. Design intent

Boxen uses a restrained **industrial cyberpunk** interface: dark machine-room surfaces, crisp cyan signal lines, selective magenta emphasis, amber caution, monospaced metadata, clipped corners, and subtle grid/scan textures. It must feel like a private inventory terminal without becoming a novelty HUD.

Usability rules override decoration:

- content typography is calm and readable;
- neon colors indicate state or action, never arbitrary decoration;
- glow is limited to focus/active states and never reduces edge clarity;
- no flashing, flickering, fake terminal typing, or continuous parallax;
- cyberpunk labels never replace plain-language primary labels;
- all core flows remain usable with motion/effects disabled.

The normative CSS values are [contracts/ui-tokens.css](contracts/ui-tokens.css).

## 2. Information architecture

### Global navigation

| Label | Route | Purpose | Roles |
| --- | --- | --- | --- |
| Home | `/` | Search/scan entry, recent boxes, pending review | All |
| Boxes | `/boxes` | Browse and filter catalog | All |
| Scan | `/scan` | Live camera, QR image, typed code | All |
| Review | `/review` | Pending AI observations | Editor, owner |
| System | `/system` | Health, model, storage, backups, users | Owner; viewer sees limited health |

Desktop uses a persistent left rail. Mobile uses a bottom navigation bar with Home, Boxes, Scan, and Review/System according to capability. Scan is visually prominent but remains a normal labeled button.

### Route inventory

```text
/login
/setup
/account
/
/boxes
/boxes/new
/boxes/:boxCode
/boxes/:boxCode/edit
/boxes/:boxCode/label
/search?q=
/scan
/review
/system
/system/users
/system/backups
/system/maintenance
```

Routing preserves query/filter state on back navigation. Unsaved editor state prompts before route loss.

## 3. Layout system

### Desktop (960 px and wider)

- Left rail: 232 px fixed column.
- Top application bar: 64 px inside the content column.
- Content max width: 1440 px; no artificial narrow column for galleries/search.
- Standard page gutter: 32 px; dense admin tables may use 24 px.
- Box detail: primary column minmax(0, 2fr), contextual rail minmax(280 px, 1fr).
- Dialog max widths: small 440 px, standard 640 px, review 840 px.

### Tablet (600-959 px)

- Collapsed 72 px icon-and-tooltip rail or top navigation depending on browser width.
- Two-column box grids where 280 px minimum card width is preserved.
- Detail contextual rail moves below primary content.
- Dialogs use viewport width minus 32 px.

### Mobile (320-599 px)

- One content column with 16 px gutters.
- 56 px top bar and safe-area-aware bottom navigation.
- No data table is required for a core flow; rows become stacked disclosure cards.
- Primary page action may be sticky above bottom navigation, but must not obscure content/focus.
- Modal flows become full-screen sheets with a visible title and close/back action.
- Editable controls use at least 16 px text to avoid browser zoom.

## 4. Visual hierarchy

### Typography

- **UI/content:** local system sans stack; 16 px base; 1.5 line height.
- **Metadata/code:** local system monospace stack; uppercase tracking only for labels of 12-13 px.
- Page title: responsive 28-36 px, weight 650-700.
- Section title: 20-24 px, weight 600.
- Card title: 17-18 px, weight 600.
- Box codes use monospaced text, normal letter spacing, and never rely on color.
- Markdown content uses a 68-character measure for prose while lists/tables may expand.

### Surfaces and edges

- Page background uses the base token with a very low-contrast 24 px grid; grid disappears in reduced-effects/high-contrast mode.
- Panels use `surface-1`; nested interactive rows use `surface-2`. Avoid card-inside-card chains.
- Standard border is 1 px neutral. Selected/focused edges use a 2 px signal color without layout shift.
- Primary panels and buttons may use one 10 px clipped corner. Inputs remain conventional rectangles for recognizability.
- Shadows are black/translucent depth only. Neon outer glow is limited to active scan/focus elements.

### Color semantics

| Color | Meaning |
| --- | --- |
| Cyan | Primary actions, selected navigation, ready/local connectivity |
| Magenta | AI-generated or AI-review content only |
| Amber | Pending, caution, archived, degraded |
| Green | Confirmed success, verified backup |
| Red | Destructive, failed, integrity/security error |
| Neutral | Ordinary content, manual inventory, inactive structure |

Every semantic color is paired with text/icon/shape. Never show state by color alone.

## 5. Shared application shell

### Desktop rail

Top to bottom:

1. `BOXEN` wordmark and compact `LOCAL NODE` descriptor.
2. Primary navigation with visible text.
3. Remaining vertical space.
4. Local status summary: green/caution/error marker plus `Local system ready/degraded`.
5. Current user menu.

Active navigation has a cyan left edge, tinted background, and `aria-current="page"`. Icons are secondary and decorative.

### Top bar

- Breadcrumb or page context left.
- Global search trigger on desktop; `/` focuses search when no editable control is active.
- `Scan code` action available on every authenticated screen.
- Pending review count is shown only when nonzero and authorized.
- No notification center, cloud status, or invented vanity metrics.

### Connectivity banner

When the API is unreachable, show one persistent amber/red banner: `Boxen host unavailable. Your unsaved changes are still on this device.` Retry with backoff. Do not imply internet connectivity is required.

## 6. Component specifications

### Buttons

| Variant | Use |
| --- | --- |
| Primary cyan | One highest-priority action per region |
| Secondary outlined | Normal actions |
| Ghost | Low-emphasis inline controls |
| AI magenta | Only `Analyze` and AI review actions; still labeled |
| Danger red | Destructive actions after clear context |

- Minimum target: 44 × 44 CSS px on coarse pointers.
- Loading state preserves label width, disables duplicate activation, and includes visible text (`Saving…`).
- Icon-only buttons require accessible names and are reserved for familiar close/more controls.
- Disabled controls explain why through adjacent text, not tooltip alone.

### Text fields and editors

- Persistent visible label; placeholder is example text only.
- Help and error text live below the field and are programmatically associated.
- Error uses red edge + icon + text; successful validation does not turn every field green.
- Markdown editor has `Write` and `Preview` tabs, a plain-text toolbar, character count, and unsaved marker.
- Raw HTML is documented as unsupported. Preview is server-equivalent sanitized rendering.

### Box card

Required visible content:

- representative thumbnail or deliberate empty state;
- box name;
- box code;
- up to three matched/representative item names when context warrants;
- item/image count;
- pending AI marker when nonzero;
- archived marker when applicable;
- updated relative time with exact time accessible.

The entire card title/thumbnail region may be one link. Secondary actions are in a labeled overflow menu and must not nest inside the link.

### Box code display

- Monospace, selectable text.
- Adjacent `Copy code` control with transient confirmation.
- Canonical hyphens always displayed; input fields normalize flexible entry.
- Checksum failure appears before network lookup.

### Inventory row/card

- Name is primary.
- Quantity/unit follows name without visual badge clutter.
- Notes preview is at most two lines in list context.
- Provenance is visible as plain `Manual`, `AI accepted`, or `Edited after AI` only in detail/edit/review contexts.
- Edit/remove/merge actions are available to editors and keyboard users.

### AI observation card

Uses a magenta top edge and explicit `AI suggestion` label. Contains image crop/thumbnail, proposed item name, quantity when present, calibrated confidence category (`Low`, `Medium`, `High`) rather than misleading decimal precision, source image link, and four actions:

1. `Accept`
2. `Edit and accept`
3. `Merge with…`
4. `Reject`

Confidence mapping is profile-calibrated and hidden when the selected model has no valid calibration. Keyboard order follows the visual order. Bulk accept is unavailable until individual confidence/duplicate warnings are resolved.

### Image tile

- Fixed aspect-ratio preview with contain/crop policy selected by context.
- Caption, ordinal, analysis state, and integrity error are outside the image.
- Broken derivative offers `Regenerate preview`; missing original is a blocking red integrity state.
- Drag reordering has equivalent `Move earlier/later` controls.

### Status indicator

Statuses are compact text-plus-symbol components. No pulsing dots except a finite scan/inference activity animation, and reduced motion removes pulsing.

### Dialog/sheet

- Native focus trap, initial focus on heading/first safe field, Escape closes unless destructive operation is executing.
- Return focus to invoker.
- Destructive confirmation states exact object and consequence; purge requires typing the exact box code.

### Toast and inline feedback

- Success toast is optional and never the only confirmation; updated content must visibly change.
- Error remains inline near the failing action and also enters an `aria-live` region.
- Toasts pause on hover/focus and are not used for destructive failure details.

## 7. Screen specifications

### 7.1 First-run setup `/setup`

**Purpose:** create the first owner and verify local prerequisites.

**Steps:** installation identity → owner credentials → data/model paths and detected capacity → local HTTPS/device trust instructions → model readiness (optional skip) → completion.

**Rules:** setup is available only when no user exists; every page explains that data remains local; password field supports paste/password manager; model skip leaves AI clearly disabled, not failed.

### 7.2 Login `/login`

- Centered compact surface, wordmark, `Local inventory node`, username/password, submit.
- No social login, registration, password reset email, or internet language.
- Generic failure copy: `Sign-in details were not accepted.`
- Rate-limit state shows retry time without identifying whether the username exists.

### 7.2a Account `/account`

- Available from the current-user menu to every role.
- Shows username (read-only), editable display name, role/status (read-only), active session expiry, and password-change form requiring the current password.
- Successful password change rotates the session and confirms that other sessions were revoked.
- Owner user-administration remains under System and is not conflated with self-service account settings.

### 7.3 Home `/`

Order:

1. Primary heading `Find what you stored.`
2. Large global search field and `Scan code` action.
3. Pending AI review callout only when count > 0 and role allows review.
4. Recently updated boxes (maximum six).
5. Compact system degradation message only when actionable.

Do not show generic KPI cards for total boxes/items unless an owner explicitly opens system status.

**Empty state:** `No boxes yet` with `Create your first box` for editor/owner; viewer sees `No boxes are available.`

### 7.4 Box browser `/boxes`

- Heading, create action (authorized), search-within-list, lifecycle filter, sort.
- Desktop: responsive card grid; optional compact list toggle remembered locally.
- Mobile: one-column cards.
- Pagination loads explicit `Load more`; no unbounded infinite scrolling.
- Filter state encoded in URL.

### 7.5 Create/edit box `/boxes/new`, `/boxes/:code/edit`

Fields: name, Markdown description. Existing box view also manages images and inventory in separate sections to avoid one giant form.

- Create action returns to detail and exposes `Print label` / `Add photos` next steps.
- Edit uses ETag; conflict page compares current server name/description with local draft and offers copy/reload/manual reapply, never blind overwrite.
- Archive is in a danger/caution zone below normal fields.

### 7.6 Box detail `/boxes/:code`

Header contains name, code/copy, lifecycle, Edit, Add photos, Analyze pending photos, and Print label according to role.

Content order:

1. Description.
2. Image gallery with per-image analysis state.
3. Confirmed inventory with search/filter and Add item.
4. Pending AI review entry when nonzero.
5. Provenance/audit summary for owner/editor, collapsed by default.

Desktop contextual rail contains label preview/action, counts, timestamps, and safe lifecycle actions. Mobile places it after primary content.

### 7.7 Image capture/upload

- Entry offers `Take photo` and `Choose files` with concise guidance: photograph one layer at a time, avoid glare, use multiple angles.
- Each file has independent preview, caption, progress, validation, retry, and remove-before-upload.
- At most three concurrent uploads; queue order remains visible.
- Success appends image to gallery. Analysis is opt-in unless owner enables a documented local auto-queue preference.
- Permission denial and unsupported camera show file chooser without dead-end messaging.

### 7.8 AI review `/review`

- Queue grouped by box, oldest first; filters for box and confidence category.
- First item is fully visible with source image and suggestion; next/previous controls preserve decisions.
- Accept action remains editable before commit.
- `Merge with…` searches only active items in the same box.
- Reject supports optional reason but no required explanation.
- Completion state links back to the box and next box with pending suggestions.
- If model is unavailable, existing observations remain reviewable.

### 7.9 Search `/search`

- Query remains in global field and URL.
- Exact code match occupies first result with `Exact code` text.
- Results show name/code/thumbnail, highlighted plain-text snippet, and matching item names.
- Matched field labels are readable (`Description`, `Item notes`).
- No results offers code normalization hints, spelling-neutral guidance, and scan action; it does not suggest internet search.
- Search degradation displays repair status and retains direct code lookup when possible.

### 7.10 Scan `/scan`

Three equal tabs: `Live camera`, `Upload QR image`, `Type code`.

**Live camera**

- Requests rear camera only after user activates `Start camera`.
- Video stays local in browser; frames are decoded client-side and never uploaded.
- Scan reticle has static corner marks and an optional slow finite scan line.
- On first valid payload: haptic feedback when supported, stop all tracks, show decoded code, resolve once, navigate on success.
- `Stop camera` is always available and runs on route departure/backgrounding.

**Upload QR image**

- Accept image file/photo; decode in browser; file is not persisted or sent to server.
- Allow retry/crop guidance on failure.

**Type code**

- Auto-uppercase and visual hyphen grouping without changing caret unexpectedly.
- Client validates syntax/checksum; server remains authoritative for existence/lifecycle.

Error states distinguish invalid syntax, checksum failure, unsupported payload version, unknown code, archived box, camera permission denied, no camera, and decode timeout.

### 7.11 Label preview `/boxes/:code/label`

- Shows exact-size preview against neutral paper background, not the cyberpunk surface.
- Profile selector displays physical dimensions.
- Preview includes box name, QR, exact code, and optional small `BOXEN` mark; never inventory contents.
- `Download PDF` is primary. Browser print is secondary and warns to use 100% scale/no fit.
- Long name behavior: two-line maximum, deterministic font reduction within bounds, then ellipsis; code/QR never shrink below scan specification.

### 7.12 System `/system`

Owner view sections: application/database, storage, worker/jobs, model profile, TLS/device trust, backup, integrity/maintenance, users, versions/licenses.

- Status uses `Ready`, `Degraded`, `Unavailable` with plain explanation and action.
- Destructive repair/restore is never one click. Restore is documented as offline CLI only.
- Viewer/editor sees only minimal non-sensitive readiness needed to understand disabled features.

## 8. Loading, empty, and error states

Every data region MUST define:

- initial loading skeleton matching final geometry;
- empty state with the next authorized action;
- stale/refetch state that keeps prior content visible;
- partial failure when one composed resource fails;
- permission-lost/session-expired state preserving unsaved local draft;
- retry action with no full-page reload requirement;
- unknown future enum fallback displayed as `Unknown state` and reported locally.

Skeletons do not animate in reduced-motion mode. No spinner runs indefinitely without text and timeout guidance.

## 9. Accessibility contract

- WCAG 2.2 AA is the release target.
- Semantic landmarks: header, nav, main, aside, footer only when present.
- One `h1` per page; heading levels do not skip for styling.
- Keyboard and screen-reader operation covers all CRUD, review, scan alternatives, label, and admin flows.
- Focus is never obscured by sticky bars/sheets and is at least 2 CSS px with strong contrast.
- Minimum target is 24 × 24 CSS px per WCAG 2.2; Boxen's product standard is 44 × 44 on coarse pointers.
- Text contrast target: 4.5:1 normal, 3:1 large; meaningful component boundaries/focus: 3:1.
- Status never depends solely on hue or animation.
- `prefers-reduced-motion: reduce` eliminates scan line, shimmer, glow transition, and layout animation.
- Zoom to 200% and text spacing overrides do not lose content/function.
- Camera has upload/type alternatives; drag reorder has buttons; hover information is also focus/touch accessible.
- Live updates use polite announcements; destructive/error updates use assertive announcements sparingly.

## 10. Motion and effects

- Standard transition: 120 ms; panel transition: 180 ms; no transition exceeds 250 ms except finite progress feedback.
- Animate opacity/transform only; never layout-affecting width/height for navigation/content.
- AI `running` may use a single subtle sweep at no more than one cycle per 2 seconds.
- Scan line is optional, no more than one cycle per 2.5 seconds, and cosmetic; decoding does not depend on it.
- No element flashes more than three times per second.
- Effects disable automatically for reduced motion and manually through `Reduce visual effects` local preference.

## 11. Content language

- Prefer `Box`, `Photo`, `Contents`, `AI suggestion`, `Scan`, `Backup` in user text.
- `Node`, `signal`, and similar cyberpunk language is limited to tertiary metadata, not task labels.
- Avoid `magic`, `smart`, or certainty claims for AI.
- AI copy: `Suggested from this photo. Review before adding to inventory.`
- Offline copy: `Everything needed is running on this Boxen host.`
- Destructive copy names exact consequence and recovery status.

## 12. UI acceptance matrix

Each screen is accepted only after:

- 320, 375, 768, 1024, and 1440 CSS px visual checks;
- keyboard-only flow;
- VoiceOver iOS and one desktop screen reader smoke test;
- 200% zoom and text-spacing override;
- reduced-motion and high-contrast/forced-color checks;
- loading/empty/error/permission/stale-ETag states;
- viewer/editor/owner authorization variants;
- outbound network blocked with browser devtools confirming no external requests.
