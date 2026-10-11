# ADR-0029: Private saved report definitions

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Saved reports can contain filters, grouping and selected columns that reveal a
user's operational interests or include data from cross-user datasets. Phase 7
requires saved report definitions but does not define their audience. The project
owner chose between creator-only visibility and sharing with scoped managers.

## Decision

In Phase 7, saved report definitions are private to their creator within the owning
organization and workspace/project scope. Only the creator may read, update, execute
or delete their saved definition. Each operation also rechecks the current access
permission required by its governed dataset. Definitions are not shared through
dashboards or links in this phase. The owner selected private visibility on
2026-10-11.

## Consequences

- Ownership is stored and checked server-side; UUID knowledge does not grant access.
- Aggregate task datasets still require scoped `schedule.manage` per ADR-0028.
- Sharing saved reports or dashboards requires a later authorization decision and
  cannot be inferred from this ADR.
- Definitions use a constrained dataset/column/filter/sort/group schema; arbitrary
  SQL and uncurated joins remain unavailable.
