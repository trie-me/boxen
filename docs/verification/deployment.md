# Deployment verification record

Date: 2026-09-20. Scope: documentation and deployment configuration for the independent local application. No publication, LAN deployment or real inventory was used.

## Evidence and provenance

| Check | Result / provenance |
| --- | --- |
| Design/source review | This deployment sidecar read `SYSTEM_DESIGN.md`, operations design, Compose/Caddy/Dockerfiles, CLI/settings, initialization, worker, backup/restore and model provisioning source. Authoritative design files were preserved. |
| Production application image | Main build reports the current image built and all primary workflows passed with `--network none`, including worker backups and AI-disabled core behavior. See [implementation status](IMPLEMENTATION_STATUS.md) and `scripts/container_smoke.py`. This sidecar did not rerun that image test. |
| Automated application checks | Main reports 121 backend tests and 7 browser scenarios passing, plus all 52 API operations covered. These are application results, not full Compose or phone qualification. |
| Compose data layout | Changed application data to `/var/lib/boxen/data` inside the volume mounted at `/var/lib/boxen`; permits the restore implementation's sibling/quarantine rename. The previous volume-root layout could not support that rename. Runtime rehearsal remains outstanding. |
| Shutdown / access configuration | Added 330-second application stop grace and explicit forwarding of `BOXEN_ANONYMOUS_ACCESS`, retaining its `viewer` default. |
| Local static checks | `docker compose -p boxen -f deploy/compose.yaml config --quiet` passed after edits. All local Markdown links in the five written documentation files resolve; `.venv/bin/boxen --help` confirms the documented command names. These checks require no running Docker services. |
| Digest pins | Existing Python, Node and Caddy base-image digest pins preserved. No registry lookup or replacement was performed by this sidecar. |
| Docker access | Unprivileged Docker inspection failed with socket permission denied. Escalated image inspection was interrupted before a result; no Docker test completion is claimed. |
| Resource cleanup | This sidecar issued no Docker create/build/run/up command and created no `boxen-qualification` container, network or volume. Nothing owned by this sidecar was left running or removed. |

## Outstanding qualification

### Main integration follow-up

The coordinating build executed the previously unused `boxen-qualification` Compose project on loopback port 18443. Startup caught and fixed three deployment defects: flow-style YAML split unquoted tmpfs options at commas; the upstream Caddy binary's file capabilities prevented execution with an empty capability bounding set; and a solely internal Docker network did not publish the host port on this Docker version. The manifest now quotes tmpfs options, removes Caddy file capabilities and listens on unprivileged container port 8443, and attaches only the TLS proxy to an ingress bridge.

After those fixes, nested-data initialization, non-root web/worker/Caddy startup, CA-certificate export, HTTPS with strict CA validation, anonymous session/browsing, owner-only user administration denial, cross-origin rejection, and served frontend all passed. Caddy's only host binding was `127.0.0.1:18443`; application services remained private. No CA was installed into a host/browser trust store. The temporary Compose resources contain only synthetic test state and are removed after verification.

### Still unverified

- Full worker restart and offline Compose restore/quarantine rehearsal with the new volume layout. Native restore/revocation/derivative repair is covered by application tests.
- Disconnected image save/load/start rehearsal and transfer checksums; same-installation host migration and full disk-loss recovery.
- Old volume-root to nested-data layout migration, if an earlier manifest has already been used with persistent data.
- Physical phone CA enrollment, secure-context camera access, permissions and live decoding; physical printer/label stock and scan durability. Simulated PDF decode/browser fixtures are not those tests.
- Actual model/runtime provisioning, quality corpus and hardware qualification. No model weights were installed.

No full release qualification is claimed. Current source also lacks the design's configurable 02:00 backup schedule, automatic 14-generation pruning, authenticated CA distribution UI, complete installation preflight and signed offline release bundle. Operational runbooks document the implemented commands and limits instead of implying these features exist.

The user removed capacity testing from scope; the coordinating build task bounded this sidecar's extended verification so integration could proceed. Subsequent Compose qualification should use a unique temporary project, loopback publication and synthetic data; inspect for existing resources first and clean up only resources created for that run.
