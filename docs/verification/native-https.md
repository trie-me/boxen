# Native HTTPS camera prerequisite

Deployed 2026-09-20 at20:46 PDT, with explicit user approval. The existing app is
now at `https://192.0.2.10:8443`. Old LAN HTTP8000 redirects GET/HEAD requests;
other methods are rejected with instructions to reload the secure address.
The isolated `/trust/` page and public CA download remain reachable over HTTP
to bootstrap phone trust. No private state is served.

## Changes and safeguards

- Added `deploy/native.Caddyfile`: explicit LAN bindings, local internal CA,
  admin disabled, automatic trust installation disabled, HTTP/1.1 and HTTP/2,
  private state separate from a public directory with exact allowed paths.
- Extracted Caddy2.10.2 from the existing local image to
  `.local/boxen-https/bin/caddy`. No downloads, global installs or mise changes.
- Changed only `origin` in `.local/boxen/app.toml`; data directory, anonymous
  editor access, model profile and local inference endpoint remain unchanged.
- Web now binds127.0.0.1:8000; Caddy binds192.0.2.10 on8000/8443. No public DNS,
  ACME, cloud tunnel, router forwarding, firewall change or host CA trust change.
- Preserved original config at `.local/boxen-https/app-before-https.toml` and a
  verified offline SQLite backup at `.local/boxen-https/pre-https.sqlite3`.
  All15 business/account/schema tables match exactly after cutover; integrity
  and foreign-key checks pass. No migration, inventory mutation or secret reset.
  Image files and the inference process were not changed.

## Verification

- `curl --cacert` validates the actual certificate chain and IP SAN and returns
  ready. No insecure TLS flags were used.
- A new opt-in `frontend/playwright.https.config.ts` test uses a disposable
  backend behind the actual Caddy configuration. The existing LAN fixture now
  accepts test-only origin/port overrides and trusts only loopback forwarding.
- The TLS browser trusts the public root in a separate NSS database mounted
  into a private bubblewrap namespace. The host trust database is not modified;
  `ignoreHTTPSErrors` is false. Anonymous creation, Secure/HttpOnly session
  cookies, enabled Start camera, synthetic getUserMedia stream and track cleanup
  all pass. Initial test failure was an incorrect tab name in the test, corrected
  to the existing `Live camera` UI label; final test passes.
- A separate read-only375px check on the live inventory verifies strict TLS,
  secure context, anonymous editor, Secure cookies, enabled Start camera and a
  synthetic stream starting/stopping, with no page errors, outbound browser
  requests or inventory mutations. Physical Motorola hardware was not tested.
- Public certificate download has the expected SHA-256 fingerprint; private-key
  requests under `/trust/` return404 over both HTTP and HTTPS.
- All174 frontend unit tests, TypeScript, formatting and changed fixture
  lint/format pass. This is deployment verification, not capacity testing or a
  rerun of real-model accuracy tests.

At verification, web326235, worker326237, proxy326239 and inference125813 were
active with zero automatic restarts. Worker/web stop grace is now330seconds to
allow bounded inference shutdown. Existing supervision remains transient, not
boot-enabled. The disposable test backend, staging proxy and extraction-only
container were stopped/removed; no user data was removed.

The user must now follow [Motorola certificate trust and camera permission](../operations/native-https.md).
Downloading the certificate alone does not install trust, and bypassing an
interstitial does not count as successful setup. The onboarding page includes
the trust implications and full public certificate fingerprint.
