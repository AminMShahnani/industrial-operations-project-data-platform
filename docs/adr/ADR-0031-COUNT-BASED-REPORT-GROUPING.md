# ADR-0031: Count-based report grouping

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

The reporting requirements call for grouping but do not define the first grouping
measure or result shape. Phase 7's initial governed dataset is overdue tasks, whose
records are authorized by the Tasks module and whose aggregate scope omits recipient
identity.

## Decision

The initial report builder supports grouping overdue tasks by task state and returns
one count per state after applying the saved report's filters and scope. Counts are
computed by a bounded grouped query in the Tasks module, not by counting a truncated
100-row report page. Groups are sorted by state value. Grouped results contain no
task, recipient, claimant or submission identifiers and do not also return row data.
Dashboard `metric` widgets may display only the total overdue count, computed as the
sum of these state buckets; metric widgets must reference a state-grouped saved
report. The report's personal or aggregate permission is rechecked at execution as
defined by ADR-0028; saved definition privacy remains as defined by ADR-0029.

## Consequences

- No user-authored expressions, arbitrary dimensions or measures are accepted.
- State filtering may produce a single group; unfiltered groups cover only states
  present in the current overdue query.
- Grouping by task kind, project, or time and additional measures require an explicit
  contract and bounded query design.
- Other metric definitions or measures require an explicit contract and bounded
  query design.
- Historical snapshots are not created; counts describe current task state at query
  time.
