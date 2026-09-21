# ADR-0001: Single-node modular monolith

- **Status:** Proposed for v1 baseline
- **Date:** 2026-09-20

## Context

Boxen must run fully locally with SQLite and local media/AI, remain operable by a non-platform team, and support a small number of concurrent local users. AI inference and media work are long-running/resource-heavy, while catalog/search requests must remain responsive.

## Decision

Use one modular application codebase and relational schema, deployed as a web process and durable worker process, with a separate loopback-only AI runtime and optional TLS proxy. Modules enforce DDD boundaries in code/tests; they do not become independently deployed services.

## Consequences

- ACID transactions can span catalog, inventory, observations, search projection, and audit.
- Deployment/backup/debugging remain small and local.
- Worker failure or model latency does not block the web process.
- Module boundaries require architecture tests because process boundaries do not enforce them.
- Horizontal multi-host scale is intentionally unsupported.

## Rejected alternatives

- **Microservices/message broker:** operationally disproportionate and creates distributed consistency for a single-host product.
- **One process including inference:** AI/resource faults can stall requests and complicate restarts.
- **Desktop-only application:** does not provide the required phone camera/scan UI.

