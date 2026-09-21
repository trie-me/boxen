# Native LAN HTTPS and Motorola Android trust

Deployed on 2026-09-20 to `/path/to/boxen`, preserving the existing
installation and anonymous editing. Server-side TLS and synthetic-camera browser
checks passed; physical Motorola trust and camera permission still require the
one-time steps below. See [verification](../verification/native-https.md).

## Deployed topology

| Component | Address or path | Purpose |
| --- | --- | --- |
| Public LAN origin | `https://192.0.2.10:8443` | Browser access through native Caddy |
| Native proxy binary | `.local/boxen-https/bin/caddy` | Caddy **2.10.2**, extracted from the existing local image |
| Application backend | `http://127.0.0.1:8000` | Loopback web process behind the proxy |
| Old LAN HTTP address | `http://192.0.2.10:8000` | Redirect to HTTPS, except public `/trust/` onboarding/downloads |
| Public CA download | `http://192.0.2.10:8000/trust/boxen-local-ca.crt` | Public root certificate only |
| Public certificate file | `.local/boxen-https/public/boxen-local-ca.crt` | Copy of this installation's CA root certificate |
| Private Caddy state | `.local/boxen-https/state` | Persistent certificates and private CA keys; never a web root |
| Existing app configuration | `.local/boxen/app.toml` | Same installation, with the exact HTTPS browser origin |

Web and worker retain the existing configured data directory, inventory, accounts,
media and local AI settings. Anonymous access remains `editor`; HTTPS does not
change who can edit. The application origin is exactly
`https://192.0.2.10:8443`, without a trailing slash. Web binds specifically to
`127.0.0.1:8000`, allowing the proxy to own `192.0.2.10:8000` separately.

This is a native proxy addition. It needs no new Compose application/volume,
global installation, mise changes, public DNS, cloud service or router port
forwarding. Keep access on the trusted LAN. The native proxy uses Caddy's internal
CA, with automatic host trust installation disabled (`skip_install_trust`).
[Caddy documents local certificate issuance and deliberate client trust](https://caddyserver.com/docs/automatic-https#local-https).

## One-time Motorola Android setup

Perform this after the deployment owner confirms HTTPS and the public download
are ready. Use the phone's personal profile and connect to the same trusted LAN
as the host. Menu names vary with Motorola model and Android version; search
Settings for **certificate** or **Encryption & credentials** if needed.

### Verify the certificate source

The host operator displays the public root's identity and SHA-256 certificate
fingerprint locally:

```sh
cd /path/to/boxen
openssl x509 -in .local/boxen-https/public/boxen-local-ca.crt \
  -noout -subject -issuer -dates -fingerprint -sha256
```

Use the SHA-256 fingerprint printed by your own installation.
Installation-specific certificate fingerprints are not published in this guide.

Get that value from the trusted host console or trusted chat with the host
operator. Compare the full certificate fingerprint, not just its display name
or a file checksum. The HTTP download and onboarding page are unauthenticated:
a fingerprint shown only on that same HTTP page cannot establish authenticity.
Only the public `.crt` file belongs on the phone; no private key or key password
is needed.

### Download and install the CA

1. On the phone, open
   <http://192.0.2.10:8000/trust/boxen-local-ca.crt> and save it to Downloads.
   The onboarding page is <http://192.0.2.10:8000/trust/>.
2. Open Android **Settings**. Search for **Encryption & credentials**. On recent
   Android builds it is under **Security & privacy → More security settings**
   (sometimes **More security & privacy**).
3. Before trusting the file, compare its SHA-256 certificate fingerprint with
   the trusted host value using certificate details, if available. If the phone
   cannot preview those details, use a direct USB copy of the host-verified file
   instead of relying on the HTTP download.
4. Choose **Install a certificate → CA certificate**. Choose the CA option,
   rather than the Wi-Fi or VPN/client-certificate option. Downloading or tapping
   the file alone does not establish CA trust on current Android.
5. Read the CA trust warning. If you accept the implications below, select
   **Install anyway**, authenticate with the phone's unlock method if prompted,
   and select `boxen-local-ca.crt`.
6. Inspect the installed entry under **Trusted credentials → User**, comparing
   its SHA-256 fingerprint with the trusted host value. Do not use Boxen if the
   identity cannot be verified; remove a mismatching certificate.

Google's [Android 11 CA-installation policy](https://developer.android.com/work/versions/android-11)
requires manual installation through Settings. Its
[CA installation walkthrough, Step 5 for Android 11 and above](https://support.google.com/device-usage-study-help/answer/15713321?co=GENIE.Platform%3DAndroid&hl=en)
confirms the CA-specific chooser and warning; only that Settings sequence applies
here. Boxen requires none of that walkthrough's study app, VPN or accessibility
setup. Google's [general certificate help](https://support.google.com/pixelphone/answer/2844832?hl=en)
documents the Settings location and removal; its installation example selects a
Wi-Fi certificate, which is a different use from Boxen's HTTPS CA.

### Open HTTPS and grant camera permission

Open <https://192.0.2.10:8443> in Chrome. It must load without a certificate
interstitial. Close or refresh the old HTTP tab and update bookmarks. This is a
new browser origin: refresh and sign in again if an old session no longer works;
ordinary anonymous editing remains available. Do not recreate the installation
or reset an account because the origin changed.

In Boxen, open **Scan → Live camera → Start camera** and allow camera access.
If Chrome previously blocked it, use **Chrome → Settings → Site settings →
Camera**, select this site and allow it. Also check Android's camera permission
for Chrome. [Google Chrome camera guidance](https://support.google.com/chrome/answer/2693767?co=GENIE.Platform%3DAndroid&hl=en).

On Motorola, ensure the **Camera access** quick-settings toggle is available,
not blocked. Motorola documents this device-wide switch separately from app
permissions in its [Android 14 user guide, “Control access to your mic and camera,” printed page 302](https://help.motorola.com/hc/7134/14/pdf/help-motorola-edge-30-fusion-14-global-en-us.pdf#page=311).
This manual is a model-specific example, not confirmation of the user's exact
phone menus. Verify the preview starts, an existing Boxen label resolves, and
stopping/leaving the scanner releases the camera. Phone reachability, trust and
camera operation remain unverified until these steps succeed on that phone.

## Trust implications and removal

A user CA grants broad trust in browsers/apps that honor the user certificate
store; it is not restricted to the Boxen address. Someone with the CA's private
signing keys could issue certificates for other sites. Android apps can use
different trust policies, so this does not mean every app accepts user CAs.
[Android network security configuration](https://developer.android.com/privacy-and-security/security-config#CustomTrust).

Protect `.local/boxen-https/state` and any backups containing it with access
limited to the service owner. Serve only the isolated public directory; never
copy private keys into it or expose the state tree through file serving or
symlinks. Retain CA state across restarts so existing device trust survives.
Replacing the CA requires a fresh fingerprint comparison and trust installation.

When retiring this installation, remove its specific user CA in Android's
credential settings. Depending on the build, select it under **Trusted
credentials → User** or **User credentials**, then remove it. Identify the entry
by fingerprint, not merely a generic Caddy name. Avoid **Clear credentials**,
which removes unrelated user certificates too. Deleting the downloaded `.crt`
alone does not remove installed trust.

## Native operator runbook

The running user services are `boxen-proxy.service`, `boxen-web.service`,
`boxen-worker.service` and `boxen-ai.service`. Treat them as **transient** unless
the deployment owner records a change: they are not a promise of startup after
reboot or a user-session shutdown. Run commands as the existing service owner.

The proxy reads `deploy/native.Caddyfile` with `LOCAL_TLS_HOST=192.0.2.10`,
`LOCAL_TLS_STATE=/path/to/boxen/.local/boxen-https/state` and
`LOCAL_TLS_PUBLIC=/path/to/boxen/.local/boxen-https/public`. Leave the test
overrides `LOCAL_HTTP_PORT` and `LOCAL_TLS_UPSTREAM` unset: their defaults are
8000 and127.0.0.1:8000. No other directories are file-served.
Web and worker use `BOXEN_CONFIG_FILE=/path/to/boxen/.local/boxen/app.toml`;
web's command now ends `web --host 127.0.0.1 --port 8000`. AI was not restarted.

Restart existing units with `systemctl --user restart boxen-web boxen-worker
boxen-proxy` only when safe to interrupt current work. A transient unit may no
longer exist after it has been stopped; use the recorded launch definitions,
not a new empty installation. Reboot startup remains a separate installation
task, not a capability established by this TLS repair.

Read current status and unit lifetime before taking action:

```sh
systemctl --user status boxen-proxy.service boxen-web.service \
  boxen-worker.service boxen-ai.service --no-pager
systemctl --user show boxen-proxy.service boxen-web.service \
  boxen-worker.service boxen-ai.service \
  -p ActiveState -p SubState -p Transient -p UnitFileState
```

Deployment sequence for the owner:

1. Preserve the existing configuration and a verified application backup using
   the [recovery runbook](recovery.md). Record the original service commands and
   bindings. This repair requires no database initialization or migration.
2. Stage the native binary, explicit LAN bindings, internal TLS and isolated
   public certificate route. Disable automatic host trust and keep proxy admin
   access off the LAN. Record the exact configuration path and service launch
   commands in the deployment handoff.
3. Coordinate web/worker changes with in-flight work. Set the exact HTTPS origin
   consistently, retain the same `.local/boxen/app.toml` and data settings, move
   web to loopback, and start the proxy on the two specified LAN listeners. Do
   not create a second worker or replace the existing AI service.
4. Run the checks below, then perform the Motorola trust/camera checks. Record
   their actual results separately from this planned topology.

These read-only host checks require no host-wide CA installation:

```sh
cd /path/to/boxen
.local/boxen-https/bin/caddy version
curl --fail --show-error --cacert .local/boxen-https/public/boxen-local-ca.crt \
  https://192.0.2.10:8443/api/v1/health/ready
curl --silent --show-error --dump-header - --output /dev/null \
  http://192.0.2.10:8000/
curl --fail --silent --show-error --dump-header - --output /dev/null \
  http://192.0.2.10:8000/trust/boxen-local-ca.crt
ss -ltn
journalctl --user -u boxen-proxy.service -u boxen-web.service \
  -u boxen-worker.service -u boxen-ai.service -n 60 --no-pager
```

Expect Caddy 2.10.2, successful certificate-verified readiness, an HTTP redirect
to the HTTPS origin, and a directly downloadable certificate. Check that HTTP
`/trust/` also works, redirected paths/queries are preserved, only public
onboarding/certificate files are served there, and the backend listens only on
loopback. Inspect worker/AI health separately; core readiness alone does not
prove those services are healthy. Verify the same inventory is visible without
creating or modifying live records. Do not publish logs containing private data.

For a routine proxy restart while its unit remains loaded:

```sh
systemctl --user restart boxen-proxy.service
```

Repeat the HTTPS check afterward. If a transient unit has disappeared, recreate
it from the owner's recorded launch definition; a guessed foreground command or
`systemctl enable` is not a substitute. To take only ingress offline, use
`systemctl --user stop boxen-proxy.service`; preserve its state and certificate.
Rollback requires stopping that proxy before returning web to its old LAN port,
restoring the saved origin/configuration consistently, and rechecking services.
HTTP rollback also loses live browser-camera access and encrypted traffic.

## QR labels and troubleshooting

Generated labels encode `boxen:v1:<canonical-code>`, and raw typed `BX-…` codes
remain independent of the origin. Existing labels need no reprint for this HTTPS
change. URL-shaped scanner input is deliberately restricted to the exact current
origin; an old HTTP URL pasted into the scanner can be rejected even if opening
it in a browser redirects. Use its printed box code instead. See
[the host-independent QR decision](../system-design/adrs/0004-host-independent-qr.md).

If the phone cannot connect, confirm its LAN, the host's current IP, both proxy
listeners and LAN firewall/client-isolation settings. If a certificate warning
persists, recheck the exact URL, phone clock, installed root fingerprint and
whether the CA state changed. Resolve trust errors before testing the camera;
do not bypass browser certificate checks or use insecure-origin flags. If HTTPS
loads but the camera does not start, check site permission, Chrome's Android
permission and Motorola's Camera access toggle. Photo upload and typed-code
lookup remain useful alternatives while diagnosing device camera behavior.
