# ADR-0041: Materialize pack KPIs as private saved reports

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 9 adds KPI artifacts to the existing reporting module. Saved reports and
dashboards are creator-private under ADR-0029 and ADR-0030, while pack content is
imported explicitly through owning services under ADR-0038. A KPI must retain its
source form semantics and current authorization when run or displayed in a dashboard.

## Decision

Import each pack KPI as a creator-private saved report in the Reporting module.
Persist the typed metric definition, exact imported form ID and form-version number,
unit, grouping field, time field and bounded window in the immutable report version.
Dashboard widgets may reference the saved report and display KPI metrics/bars. Every
execution rechecks scoped `submission.read` through the Submissions application
service. KPI report definitions are immutable after import; a user may rename or
archive the private report using existing report operations.

## Consequences

- KPI artifacts do not introduce a second persistence, ownership or audit model.
- Source form versions remain pinned; changing or retiring a form does not rewrite a
  saved KPI definition.
- Form permissions and availability are checked at execution time; an unpublished,
  retired or unauthorized source form produces no aggregate result.
- KPI outputs remain aggregate-only and inherit the 366-day and grouping limits in
  ADR-0040.
