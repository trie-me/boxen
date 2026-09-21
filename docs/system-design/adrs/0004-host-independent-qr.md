# ADR-0004: Host-independent QR payload

- **Status:** Proposed for v1 baseline
- **Date:** 2026-09-20

## Context

Labels should survive changes to host IP, local hostname, TLS certificate, and deployment. Encoding a local URL improves system-camera behavior but makes every physical label dependent on network configuration.

## Decision

Generate the canonical payload `boxen:v1:<BoxCode>`. The in-app scanner decodes and resolves it. The exact canonical `BoxCode` is printed in human-readable form. The parser may accept a configured Boxen local URL as an input alias, but generated labels never use that alias in v1.

## Consequences

- Labels remain valid for the life of the box and across restore/migration/host changes.
- Live scan requires the Boxen web app rather than relying on arbitrary system-camera URL opening.
- QR image upload and typed-code paths use the same resolver.
- The scheme/version permits future compatible payload evolution.

## Rejected alternatives

- **Local URL in QR:** fragile under hostname/IP/TLS changes.
- **Database row ID:** leaks implementation identity and risks reuse/migration coupling.
- **Opaque random QR unrelated to printed code:** undermines manual fallback and human verification.

