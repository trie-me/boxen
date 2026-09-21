# HTTP API Specification

## 1. Contract authority

The machine-readable contract is [contracts/openapi.yaml](contracts/openapi.yaml), authored as OpenAPI 3.1.2 with JSON Schema 2020-12 semantics. Version 3.1.2 is intentionally selected for mature framework/code-generation support; moving to a later OpenAPI feature set requires an ADR and toolchain proof. This document defines conventions and behaviors that OpenAPI cannot fully express.

All browser/API traffic uses the same local HTTPS origin and base path `/api/v1`. There is no public cross-origin API in v1.

## 2. Protocol conventions

| Concern | Contract |
| --- | --- |
| Media type | JSON requests/responses use `application/json`; errors use `application/problem+json` |
| Character set | UTF-8; invalid UTF-8 is rejected |
| Time | RFC 3339 UTC strings ending in `Z` |
| IDs | UUIDv7 strings except public `BoxCode` |
| Quantity | Decimal JSON string with up to three fractional digits |
| Pagination | Opaque cursor plus bounded `limit` (default 50, maximum 100) |
| Versioning | URI major version `/api/v1`; additive fields are allowed within v1 |
| Request correlation | Client MAY send `X-Request-ID`; server returns a validated/generated ID |
| Optimistic concurrency | Resource ETag + mandatory `If-Match` for mutable existing resources |
| Idempotency | `Idempotency-Key` required for create, upload finalization, analysis request, backup request, and observation decision |
| Cache | Authenticated JSON defaults `Cache-Control: no-store`; hashed static assets are immutable |

Unknown JSON properties are rejected for mutation schemas. The server may add response fields within v1; clients MUST ignore unknown response properties.

## 3. Authentication and CSRF

### Session cookie

- Cookie name: `boxen_session`.
- Opaque random token; only a SHA-256 token hash is stored server-side.
- Attributes: `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`.
- Idle timeout: 12 hours; absolute timeout: 7 days; owner may configure stricter values.
- Session rotation occurs after login, password change, and privilege change.

### CSRF

Authenticated state-changing requests MUST include `X-CSRF-Token`. The token is obtained from `GET /api/v1/session`, is bound to the server-side session, and is never placed in a cookie readable by JavaScript. The server also requires `Origin` to equal configured `BOXEN_ORIGIN` for browser mutations.

### Login

- Login failure returns the same status/body for unknown user, disabled user, and wrong password.
- Rate limits are keyed by normalized username and client address, persisted across process restart for the active window.
- Successful login replaces any anonymous session and returns current user/capabilities.

## 4. Authorization behavior

The OpenAPI operation descriptions identify minimum roles. The server uses default deny.

- Unauthenticated access is limited to liveness/readiness and login bootstrap endpoints.
- `viewer` can read/search/scan/download display media.
- `editor` adds all catalog, media, inventory, AI review, and label operations.
- `owner` adds users, backup, repair, purge, and configuration operations.
- A resource that exists but is not visible under the caller's policy returns `404` where disclosing existence would add risk; role-only denials return `403`.

## 5. Errors

Every non-2xx application error uses RFC 9457 Problem Details:

```json
{
  "type": "urn:boxen:problem:box.version_conflict",
  "title": "The box changed in another session",
  "status": 412,
  "detail": "Reload the current box before saving your changes.",
  "instance": "/api/v1/boxes/BX-7K3M-R9QA",
  "code": "box.version_conflict",
  "request_id": "0199...",
  "errors": [
    {"path": "/name", "code": "value.too_long", "message": "Use 120 characters or fewer."}
  ]
}
```

- `type`, `title`, `status`, `code`, and `request_id` are always present.
- `detail` is safe for end-user display and never includes stack traces, SQL, paths, model prompts, or secrets.
- `errors` is present only for field/batch errors and uses JSON Pointer paths.
- Validation is `422`; malformed JSON is `400`; unauthenticated is `401`; unauthorized is `403`; not found is `404`; lifecycle/state conflict is `409`; missing precondition is `428`; stale precondition is `412`; rate limit is `429`; unavailable dependency is `503`.
- `429` and retryable `503` include `Retry-After`.

## 6. Resource conventions

### Box detail

Box detail is the primary composed resource. It includes catalog fields, image summaries, confirmed inventory, pending observation count, and allowed actions. Large original images, raw AI output, full audit, and binary label bytes are separate endpoints.

### Markdown

Mutation payloads contain only Markdown source. Responses contain source for editors/owners plus server-rendered sanitized HTML and plain text as documented. Viewers do not require source but v1 may include it because local users share the same trust domain; authorization tests still guard user management/admin data.

### Images

Upload uses `multipart/form-data` with one `file` part and optional `caption`. The endpoint returns only after the image reaches `ready` or validation fails. Multiple selection in the UI is implemented as bounded parallel single-file requests, which gives each upload an independent idempotency key and error state.

`GET /images/{id}/content?variant=thumbnail|display|original` streams authorized bytes with content type, length, ETag equal to content hash, `nosniff`, and private cache headers. `original` requires editor role.

### Analysis

Analysis request returns `202 Accepted` with a durable job. The UI polls the job using bounded exponential backoff (1, 2, 3, then 5 seconds, maximum 5) and stops on terminal state or page departure. Polling supports `If-None-Match` and may return `304`.

### Observation acceptance

Acceptance body uses exactly one mode:

- `create`: create an inventory item using editable proposed/default fields;
- `merge`: link into an existing item, optionally updating that item under its ETag.

The operation atomically transitions the observation and inventory. A repeated identical idempotent request returns the prior success. A different decision on a decided observation returns `409`.

### Search

Search text is ordinary user text, not raw FTS syntax. The response identifies `matched_fields`, plain-text snippets with ranges, matching item summaries, score, and exact-code flag. Scores are only meaningful within one response and are not a public ranking API commitment.

### Labels

PDF responses include `Content-Disposition: attachment; filename="<safe-name>-<code>.pdf"`. Label rendering is deterministic for `(box version, profile key/version, renderer version)` and uses an ETag over those inputs.

## 7. Endpoint inventory

### Authentication and users

- `GET /setup/status`
- `POST /setup/owner`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /session`
- `PATCH /session/profile`
- `POST /session/password`
- `GET /users`
- `POST /users`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`

### Boxes, media, and inventory

- `GET /boxes`
- `POST /boxes`
- `GET /boxes/{box_code}`
- `PATCH /boxes/{box_code}`
- `POST /boxes/{box_code}/archive`
- `POST /boxes/{box_code}/restore`
- `POST /boxes/{box_code}/purge`
- `GET /boxes/{box_code}/images`
- `POST /boxes/{box_code}/images`
- `GET /images/{image_id}`
- `PATCH /images/{image_id}`
- `DELETE /images/{image_id}`
- `GET /images/{image_id}/content`
- `PUT /boxes/{box_code}/image-order`
- `GET /boxes/{box_code}/items`
- `POST /boxes/{box_code}/items`
- `GET /items/{item_id}`
- `PATCH /items/{item_id}`
- `DELETE /items/{item_id}`
- `POST /items/merge`

### AI analysis and review

- `POST /images/{image_id}/analyses`
- `GET /jobs/{job_id}`
- `GET /analysis-runs/{run_id}`
- `GET /boxes/{box_code}/observations`
- `POST /observations/{observation_id}/accept`
- `POST /observations/{observation_id}/reject`

### Discovery and labels

- `GET /search`
- `POST /codes/resolve`
- `GET /label-profiles`
- `GET /boxes/{box_code}/label.pdf`

### Operations

- `GET /health/live`
- `GET /health/ready`
- `GET /system`
- `GET /backups`
- `POST /backups`
- `GET /backups/{backup_id}`
- `POST /backups/{backup_id}/verify`
- `POST /maintenance/search/verify`
- `POST /maintenance/search/rebuild`
- `POST /maintenance/media/verify`
- `GET /maintenance/{job_id}`

Restore is deliberately CLI/offline-only in v1 and therefore has no HTTP endpoint.

## 8. Rate and resource limits

| Operation | Default limit |
| --- | --- |
| Login | 5 failed attempts per normalized user/client per 15 minutes |
| JSON body | 1 MiB |
| Image upload | 25 MiB compressed, 50 megapixels decoded |
| List/search page | 100 records maximum |
| Search query | 256 Unicode scalar values |
| Concurrent uploads per session | 3 |
| Pending analysis jobs per installation | 500 |
| Analysis requests per image/profile/prompt | One non-terminal equivalent |
| Label generation | 30 per minute per user |

Limits are advertised by `GET /system` and failures use stable problem codes.

## 9. Compatibility policy

- Breaking HTTP changes require `/api/v2`.
- Additive response fields and new enum values MAY appear in v1; clients must tolerate them where the schema marks extensibility.
- Request schemas reject unknown fields to catch client mistakes.
- Deprecated v1 fields remain for at least one minor release and include a response `Deprecation` header plus documented replacement.
- Frontend and API are released together, but contract tests still treat them as independent consumers.

## 10. API verification

Release gates include:

- OpenAPI schema validation and linting;
- implementation route/operation ID parity;
- generated TypeScript client compilation;
- response conformance for success and every documented error class;
- role matrix tests per operation;
- ETag/`If-Match`, CSRF, Origin, idempotency, pagination, rate-limit, and upload boundary tests;
- backward-compatibility diff against the last released v1 contract.
