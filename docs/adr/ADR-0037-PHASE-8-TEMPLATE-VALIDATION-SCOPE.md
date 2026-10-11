# ADR-0037: Phase 8 template validation scope

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

The Domain Pack architecture lists forms, master data, workflows, automations,
reports, dashboards, roles, integrations and mappings as possible content. It does
not define a pack-local stable artifact ID schema, a cross-file reference syntax,
or how an expression-bearing pack template maps to the existing module contracts.
The Phase 8 validator currently enforces the typed manifest, checksums, package
path/size/syntax limits and the accepted typed migration allowlist. It does not
materialize templates or execute pack content.

## Proposed decision

Keep Phase 8 template validation limited to bounded syntax, exact checksums, package
structure and typed migration descriptors. Defer template-specific expression,
schema and cross-artifact reference validation until stable pack artifact schemas
and reference conventions are defined. Do not infer artifact IDs from file names or
execute unvalidated content. Complete schema-specific validation with the phase
that defines and materializes the corresponding pack artifacts.

## Consequences

- Phase 8 can safely catalog and install pack release provenance without pretending
  unsupported templates are ready to materialize.
- The SDK cannot yet promise semantic validation of form/workflow/etc. template
  content or resolution of cross-artifact references.
- The owner must accept or replace this scope before P8-07 can be accepted.

The project owner accepted this recommendation on 2026-10-11. Template-specific
schema/expression/reference validation belongs with the phase that defines those
pack artifact contracts (currently planned with the Phase 9 starter pack).
