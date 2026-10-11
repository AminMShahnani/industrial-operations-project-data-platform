# ADR-0033: Overdue backlog by due-date week

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 7 asks for trend and line widgets. Task records preserve current state and
due timestamps but not timestamped state transitions, so a historical state trend
cannot be reconstructed from current rows. The project owner selected a view of
current overdue counts by due-date week.

## Decision

The governed overdue-task dataset may group currently overdue tasks into UTC
Monday-start calendar weeks. The chart covers the current UTC week and the prior
11 weeks, plus one `older` bucket for earlier due dates. The reporting application
anchors the window and as-of time once per query. The Tasks service returns the
aggregate in one SQL statement. All 12 week buckets are returned, including zero
counts, in chronological order after `older`. Counts are evaluated at request time
and include only current overdue-eligible states (`open`,
`in_progress`, `returned`). The Tasks service applies the same personal or scoped
`schedule.manage` authorization and filters as overdue rows.

Creator-private saved reports may pin this grouping, and private dashboard trend
and line widgets may consume it. The grouping returns no task or person identity.
It does not represent historical snapshots, state transition volume or completion
rate. Existing state-count bar and metric widgets retain their current contracts.

## Consequences

- Results have a fixed maximum of 13 buckets and a stable UTC axis.
- A current query can change historical due-week counts when a task changes state;
  the report is not a historical snapshot.
- Accurate state-at-time and completion trends require a separate immutable event
  or snapshot model and explicit migration/retention design.
