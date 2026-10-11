# ADR-0039: Phase 9 version-neutral internal mapping profiles

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

The Oil & Gas starter brief reserves mapping layers for WITSML-compatible well/site
data and drilling-report standards but selects no standard version, profile or
conformance level.

## Decision

Phase 9 may provide declarative, typed mapping profiles between the starter pack's
internal artifact fields and explicitly named internal import/export fields. It does
not claim compatibility or conformance with WITSML or any external drilling-report
standard. External adapters require a separately selected target/version and
conformance decision.

## Consequences

- Mapping profiles are inert data and contain no executable transforms.
- Unsupported or unselected external standard identifiers are rejected rather than
  guessed.
- Phase 9 acceptance concerns internal, versioned mapping contracts only.
