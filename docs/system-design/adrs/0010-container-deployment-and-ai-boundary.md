# ADR-0010: Container deployment and an optional remote vision boundary

Status: accepted for implementation, 2026-09-21. Independent application.
Source checkpoint before this work: `237c111`, annotated tag `rev1-checkpoint`.
This decision supersedes the loopback-only AI topology where noted; it does not
change inventory authority, review semantics or the small-user scope.

## Decision

Ship one application image, reused by the HTTP API, one background worker and
explicit administrative commands. Serve the packaged frontend from the API.
Use a separate local HTTPS proxy image and an optional inference image. Do not
put a process supervisor, model weights, Node, package installers at startup, or
a second database service in the application container.

| Process | Responsibility | Durable access | Network |
| --- | --- | --- | --- |
| Proxy | TLS and same-origin forwarding | Its own CA/config volumes | Published HTTPS only |
| Web | UI, authentication, uploads, inventory, enqueue jobs | Application data read/write; local model profile read-only when enabled | Private Compose network |
| Worker (one) | SQLite job claims, AI calls, maintenance, backups | Same application data; model profile read-only | Private Compose network |
| Local inference | Execute a provisioned vision model | Models/runtime read-only, no inventory or session secrets | Private network, no published port |
| Init/maintenance | Explicit schema setup, backup, integrity and offline restore | Application data read/write | One-off process |

One codebase and one SQLite queue are enough here. Redis, Kubernetes, a database
server, API replicas and concurrent inference slots add no benefit for the
intended household/small-user workload. A stopped AI service must not stop
manual inventory, search, photo uploads, QR lookup or printing.

The local AI image adds native runtime libraries to the application image;
weights and the checksum-pinned executable remain provisioned files. This is
an initial packaging choice, not a requirement that future GPU images contain
the whole application. Model hardware, runtime and image versions can evolve
independently of the web/worker image.

## Storage boundary

Mount the application volume at `/var/lib/boxen`, with the active installation
under `/var/lib/boxen/data`. SQLite, its WAL/SHM, originals, derivatives, secrets
and backups belong to the same local filesystem. Restore can atomically rename
the child directory and retain a sibling quarantine. Do not mount the database
file alone or mount the active child as a filesystem root. Do not use NFS/SMB.

Keep model artifacts under a separate `/models` read-only mount. Local web and
worker currently also verify those artifacts at startup; they share the same
read-only volume rather than copying weights into their images. This does add
startup disk reads. A later signed runtime-attestation protocol could remove
that coupling; this revision does not claim such an attestation exists.

See [volume and configuration specification](../../operations/container-storage.md).

## Optional remote inference

Support an administrator-selected **OpenAI-compatible vision server** as an
explicit alternative (`BOXEN_AI_MODE=remote`). It is not a browser-supplied URL,
cloud fallback, arbitrary provider integration or automatic photo export.
The configured server must support the documented model-discovery, multimodal
chat and bounded JSON-schema response contract. The browser still talks only
to Boxen. Only requested analysis sends a resized, metadata-stripped JPEG and
the inventory prompt to that server; manual inventory remains local.

The default remains local, with local endpoint restrictions and no required
internet. Remote mode permits a separately managed LAN/GPU machine or a server
outside the LAN. HTTPS certificate verification is mandatory by default;
an explicit insecure-HTTP setting exists only for an operator's trusted network.
Bearer credentials and custom CA bundles are read from mounted files. Redirects,
environment proxy discovery and insecure TLS bypasses are not enabled.

Remote profiles contain declared model/runtime identities and real artifact
digests, not local weights. These are **operator-reported**, not evidence that
the remote server actually loaded those weights. Record this distinction in run
provenance and display that remote inference is configured. Do not fabricate
digests from model names to satisfy the existing schema. A provider without
the required identity and response contract is not supported by this adapter.

The deployment must explicitly add outbound routing for remote mode. The
offline indicator is false in this mode, even for an endpoint on the LAN: Boxen
no longer promises all execution happens on the same host. Users must see the
remote-analysis notice near the Analyze controls. Existing pending suggestions
still require the same review/accept flow. Endpoint changes should happen after
draining or cancelling queued jobs; profile IDs must not be reused for a
different model.

## Distribution and compatibility

Base Compose describes image-only deployment; a source-build overlay is a
separate concern. Image references are configurable for a future Docker Hub
namespace, version tag or immutable digest. No namespace has been selected,
no registry push is implicit, and no image is described as published yet.

Initially qualify Linux amd64 images and the existing CPU model profile. Docker
Desktop can run Linux images, but native macOS/Windows and ARM/GPU inference
are not thereby qualified. Multi-platform publication requires per-platform
image build, dependency checks and real inference; do not publish an untested
architecture manifest. Install/provision/pull may require internet; normal
local-mode execution must not.

## Verification gates

- Clean source checkpoint before packaging; no secrets, photos, certificates or
  model artifacts in Git or the Docker build context.
- Build images; run non-root with read-only root, explicit writable volumes,
  bounded temporary storage and no added capabilities.
- Disposable HTTPS Compose installation: anonymous CRUD, upload, search, label,
  protected administration, worker heartbeat, persistence across recreation.
- Separate network-disabled image smoke for core workflows and backups.
- Optional inference container: real fixture photo produces reviewable items;
  no inventory appears until explicit acceptance; no user photo is used.
- Remote adapter tests: explicit opt-in, URL validation, TLS/auth files, no
  redirects, bounded responses, truncation retry and honest provenance.
- No capacity/load testing requirement. Record unsupported platforms and
  untested physical phone behavior rather than imply coverage.

Operational background: [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
persist outside container lifetimes; [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)
allow optional services. Multi-architecture publication follows Docker's
[multi-platform build model](https://docs.docker.com/build/building/multi-platform/).
