# ADR-0003: Human-reviewed local AI observations

- **Status:** Proposed for v1 baseline
- **Date:** 2026-09-20

## Context

General images of crowded boxes are ambiguous. Local models can miss, duplicate, or invent objects, and model/runtime capabilities change rapidly. User-confirmed inventory must remain trustworthy.

## Decision

Run a pinned local multimodal model through a narrow adapter. Store immutable run provenance and pending observations. Only an explicit editor decision may create/merge confirmed inventory. Model, prompt, schema, preprocessing, and runtime changes are separately versioned and evaluation-gated.

## Consequences

- AI can improve entry speed without becoming the source of truth.
- Review UX is a first-class product surface, not error cleanup.
- Re-analysis is safe and never overwrites user edits.
- Model availability/quality can evolve behind stable domain/API contracts.
- Fully automatic inventory is deliberately not provided in v1.

## Rejected alternatives

- **Auto-accept model output:** unacceptable hallucination/data-corruption risk.
- **Cloud vision API:** violates runtime locality/privacy.
- **Fixed model embedded in domain code:** couples product state to a volatile runtime/model.

