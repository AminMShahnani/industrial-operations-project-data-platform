# ADR-0036: Phase 8 declarative migration allowlist

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

ADR-0035 requires typed allowlisted migration content and rejects executable
migrations. The architecture defines major-version migration review but does not
name operations or expose atomic migration services from Forms, Workflows, or Master
Data. Running transformations now would require guessing artifact ownership and
reference semantics.

## Decision

Phase 8 migration files are review-only declarative descriptors. The v1 allowlist is
limited to `deprecate_artifact` and `add_optional_field`, each with a typed artifact
kind, stable artifact ID and bounded field ID where applicable. Descriptors cannot
contain expressions, scripts, SQL, path references or free-form operation payloads.
Unknown keys and operation kinds are rejected. They are checksum-pinned with the
release and exposed in the install/upgrade review plan, but are not automatically
executed in Phase 8. Pack content materialization and migration execution wait until
the owning module offers atomic, auditable application services and reference checks.

## Consequences

- Major-version upgrades can be reviewed against a constrained, stable operation
  vocabulary without introducing an execution engine.
- Current install/upgrade applies immutable release provenance only; it does not
  silently mutate forms, workflows, master data or operational records.
- The allowlist can be extended only with explicit typed schemas and tests.
- Deferred migration execution and artifact provenance are recorded as Phase 8
  limitations, not inferred from descriptive pack content.

The project owner accepted the recommended v1 allowlist on 2026-10-11.
