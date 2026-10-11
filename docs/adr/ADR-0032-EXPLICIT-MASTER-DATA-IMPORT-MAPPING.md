# ADR-0032: Explicit master-data import mapping

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 7 requires import mapping and review, while the existing Master Data
transfer already supports bounded CSV/XLSX preview and create-only application.
The import contract must support customer column names without allowing arbitrary
schema fields or turning imports into an update path.

## Decision

Imports may map each source header to at most one declared built-in or dynamic
master-data field, and each target may be assigned at most once. `code` and
`name` are required; unmapped source columns are ignored. Mapping entries are
explicit and ordered in the request, and their canonical JSON SHA-256 is bound
to the apply confirmation along with the file SHA-256 and immutable type
definition version. Existing canonical-header imports may omit an explicit
mapping. Noncanonical files first return source headers for mapping during dry
run; they cannot be applied until a mapped preview succeeds.

Imports remain create-only. Source `id` values are ignored and new record IDs
are generated. Duplicate codes reject application. All writes continue through
the Master Data service validation and immutable audit events.

## Consequences

- A changed file, mapping, or type version invalidates apply confirmation.
- No migration or existing-record rewrite is required.
- Mapping does not support formulas, arbitrary expressions, field creation, or
  record updates.
- Reusable mappings, asynchronous imports, and larger files require a separate
  bounded contract and idempotency design.
