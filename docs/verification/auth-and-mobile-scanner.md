# Authentication feedback and mobile QR recovery

Date: 2026-09-20. Independent local application.

## Reproduced defects and boundaries

The API's validation responses contained a field-error array, but `ApiError`
discarded it. Forms had no inline field-error rendering, leaving users with
"check the highlighted fields" and no highlighted fields. Header validation,
including a short setup token, also reported a root path instead of identifying
the header. Browser coverage previously started with an owner already created;
it did not exercise first-owner creation through the form.

The live installation reported `setup_required: true` during read-only checks.
Its first-owner account has not been created by these repairs. No real login
attempts, user creation/reset, token rotation or credential disclosure were used
for testing. A failed short-token request is a reproduced cause of the generic
message, not a claim about which value the user entered.

For the Motorola Android report, the actual LAN page is HTTP. Read-only browser
inspection confirmed an insecure context with no `mediaDevices/getUserMedia`,
an intentionally disabled live Start camera button, and a camera-allowing
Permissions Policy. HTTPS is still required for continuous browser-camera access.
No phone certificate trust or networking configuration was changed.

QR image decoding had unbounded promises with no worker-error/messageerror
handling and a single overwritable callback. A failed/hung worker could leave the
UI busy silently; repeated file selection was not reset. These failure modes
are reproduced with injected failures. The user's exact physical phone/photo
failure is not claimed reproduced.

## Repairs

- Preserve bounded, structured API field errors and show their details globally.
- Mark setup/login/re-authentication inputs invalid with associated inline messages;
  focus the first invalid field, preserve entered values, and match client rules
  to server limits. Password bytes are never trimmed or normalized.
- Read actual form values so password-manager/autofill changes are submitted even
  without framework change events. Trim only non-password fields.
- Show setup-token guidance, account-status loading/retry states, and meaningful
  required/length/type messages. Header/query/path errors carry escaped paths;
  error text never contains submitted password or token values.
- Keep setup-token checks, password requirements, common-password rejection,
  authentication/CSRF/rate limits and anonymous permissions unchanged.
- Add `Take QR photo` with a native file-capture hint and keep uploaded-photo and
  typed-code alternatives. The picker may offer the phone's camera or file selection;
  this does not make HTTP a secure context or guarantee a permission prompt.
- Load QR photos locally through an image element, avoiding an ImageBitmap
  requirement and handling tested EXIF orientation. No external decoding.
- Give decoder/image/lookup/camera-opening operations deadlines, IDs, cancellation,
  visible progress/errors and fresh-reader retries. Same-file retries work.
- Stop camera tracks on method changes, navigation, hidden-page transitions,
  cancellation and late permission grants. Ignore stale operations/replies.

## Verification

Tests use disposable databases and test-only credentials. The dedicated auth
browser fixture creates the first owner through the real HTTP endpoint, then
logs out and back in. It covers multiple invalid inputs, an actual server header
validation error, wrong token, preserved drafts, password whitespace and autofill.
The backend suite adds 33 auth-validation and security regressions.

Scanner tests decode actual PNG and EXIF-oriented JPEG labels, exercise native
capture input attributes, constructor/worker/message/init/decode failures,
same-file recovery, invalid/cancelled input and camera lifecycle races. Supplying
a capture input file in automation is not a physical Android-camera test.

Final results on the combined build:

- Backend:359 passed,2 opt-in real-model tests skipped;59/59 API operations have
  successful coverage (`artifacts/tests-auth-validation.xml`).
- Frontend:132 unit tests passed. TypeScript, Python lint/format/type checks and
  frontend formatting/build passed.
- Browser:1 first-owner/authentication scenario,14 dedicated scanner scenarios,
  9 LAN/organization scenarios and7 baseline scenarios passed (31 total).
  Dedicated scenarios are intentionally skipped by the baseline configuration,
  then run by their own configurations; skips are not counted as passes.
- Invalid-auth and HTTP-scanner phone layouts passed automated WCAG A/AA checks
  with no horizontal overflow; screenshots were visually inspected. Permission
  and camera-track tests use synthetic browser fixtures, not a physical camera.

Dedicated configuration commands (set `BOXEN_TEST_FRONTEND_DIR` to the staged
build and `CHROME_BIN` to the installed Chromium when needed):

```sh
pnpm --dir frontend exec playwright test --config playwright.auth.config.ts
pnpm --dir frontend exec playwright test --config playwright.scanner.config.ts
```

Baseline and LAN suites remain separate. See `artifacts/tests-auth-validation.xml`,
`frontend/test-results-auth/` and `frontend/test-results-scanner/` for generated
evidence. Device capture behavior varies; [HTML capture documentation](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture)
and [camera secure-context requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
explain the distinction. No capacity or physical-phone qualification is claimed.

## Local deployment

The tested `.local/auth-validation-build` was promoted to the existing static
directory with old hashed assets retained and `index.html` copied last. Previous
index: `.local/auth-validation-previous-index.html`. Generated files matched byte
for byte, including a rebuild after a source-only formatting correction.

At19:59 PDT on2026-09-20, the LAN application at
`http://192.0.2.10:8000` reported ready. Only `boxen-web.service` restarted
(PID274755); worker237431 and inference125813 were unchanged, all active with
zero automatic restarts. No database migration, inventory edits, credential
changes, global dependency installation or networking changes were performed.

Read-only live Chromium at375px confirmed setup-token help, no phantom invalid
fields before submission, enabled native capture, disabled HTTP live-camera
start, no empty camera preview and no horizontal overflow. No page errors or
external requests occurred. Setup was still required; actual account creation
remains the owner's action. The services remain transient, not boot-enabled.
