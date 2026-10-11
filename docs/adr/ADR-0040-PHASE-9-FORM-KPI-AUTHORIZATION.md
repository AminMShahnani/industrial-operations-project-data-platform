# ADR-0040: Phase 9 form KPI authorization and bounded results

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 9 Domain Pack KPI definitions aggregate submitted form values. ADR-0028
requires scoped `schedule.manage` for aggregate task reports, but that permission
does not grant access to form submissions. The existing submissions boundary uses
`submission.read` for cross-user reads. KPI results must not reveal submitter
identity or bypass form-version field permissions.

## Decision

Form KPI evaluation requires scoped `submission.read` for the source form's exact
workspace or project scope. The query covers only submitted records for the exact
source form and an explicitly bounded window of at most 366 days. It returns
aggregate values only; submitter identity and individual submissions are excluded.
KPI field references must be validated against the imported published form version
and its field kinds before execution. Authorization is checked by the owning
application service on every execution.

## Consequences

- `submission.read` grants aggregate access only within the same scope where it is
  already granted; it does not grant access to draft or individual submission data
  through the KPI interface.
- Pack KPI artifacts cannot select fields outside the exact source form version.
- Aggregate outputs contain no owner, submitter, or submission identifiers.
- No permission or data path for cross-tenant, cross-workspace, or cross-project
  aggregation is introduced.
