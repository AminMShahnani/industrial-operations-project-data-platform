# ADR-0013: Periodic timer and task deadline events

Date: 2026-10-06
Status: Accepted; implements docs/11–12 under ADR-0009 and ADR-0011

## Decision
Use explicit, preview-first scoped operator batches and the existing audit/outbox
pipeline. No new worker authority or scheduling framework is introduced. Each apply
checks the configured issuer's persisted identity and current scope management
permission. Timer generation additionally checks the pinned activating administrator's
current organization and rule-scope authority; execution keeps its existing fresh checks.

Each immutable active timer definition owns its cadence. Its UTC slots are
`timer_start + n * timer_seconds`, starting at the first slot at or after activation.
Do not backfill pre-activation slots. One invocation emits at most 100 occurrences
for one exact rule/version, with `more` and `next_at` for bounded downtime catch-up.
Never silently skip the backlog or follow another version's progress. A retired
version stops generation; a new version starts from its own activation boundary.
Lock the owning rule/version, retain immutable occurrence evidence and uniquely
constrain version/slot. A timer event matches only its exact pinned version, not
every timer rule in the same scope. Database run guards enforce that binding too.

Task due/overdue belongs to the task module. Due is reached at `now >= due_at`;
overdue starts at `now > due_at`. Only open, in-progress or returned tasks qualify,
matching the existing overdue view. Retain at most one event of each kind per task;
later return/retry never invents a new occurrence or rewrites its immutable deadline.
A late tick emits both missing events in due-then-overdue order. Deadline events
record the immutable deadline separately from detection time; they do not mutate
task lifecycle/revision. Completed, review-waiting, cancelled and superseded work
does not receive retrospective deadline events.

A deadline batch reads at most 101 pending tasks and processes the first 100. Query
filters exclude completed deadline evidence before pagination. Apply locks rows with
SKIP LOCKED, so task completion/cancellation and concurrent ticks serialize safely;
the next periodic scan starts without a cursor to revisit skipped rows. The optional
cursor continues a bounded page, not a permanent watermark. Emit events, audits,
matched pinned runs and immutable deadline marks in the same transaction.

Periodic source events carry typed IDs, exact form/timer pins and scheduled_at,
never submission values or private draft IDs. Task conditions can use allowed task
metadata; an unfinished task's private draft is not a condition lookup source.
Timer form pins, when configured, constrain matching metadata and do not invent
submission data. Their form-value conditions receive no captured form values.
Actions retain their existing authorized owning-service contracts. Source occurred_at
is actual detection time; scheduled_at records the deadline/slot, so delayed actions
derive due dates from the immutable captured event, rather than retry wall-clock time.

## Persistence and rollback
Add immutable timer occurrence and task deadline evidence tables with composite
tenant keys, exact outbox/audit/source proof guards, uniqueness and update/delete/
truncate protection. No existing artifact, task, run or audit row is rewritten.
Empty downgrade is reversible. Populated downgrade refuses before any removal;
stop periodic generation and preserve history through a reviewed forward fix or
verified database restore with an explicit write-replay plan. Never delete event
evidence or disable guards to force downgrade. Already captured runs retain their
original delegation and exact version when a definition retires.
