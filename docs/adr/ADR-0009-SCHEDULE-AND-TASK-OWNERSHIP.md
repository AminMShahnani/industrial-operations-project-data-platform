# ADR-0009: Schedule materialization and task ownership

Status: Accepted
Date: 2026-10-06

## Context
Phase 4 implements docs/03 FR-030 through FR-034 and docs/11. Schedules,
occurrences and submissions are distinct aggregates. Definitions specify timezones;
occurrences retain exact form/schedule versions and assignment snapshots. Recipients
may be users, scoped roles, teams, departments or shifts. Existing scope policies
and private draft ownership must remain enforced.

docs/11 does not say whether group recipients share one work item or each owe a
separate completion. This is a product and authorization decision: it determines
who may claim, who owns the resulting draft, how completion satisfies an assignment,
and what uniqueness means under concurrent materialization. Do not silently choose.

## Decision
The user selected the recommended shared-task option on 2026-10-06. Q-004 is resolved.
Q-004 asks the user to select:
1. Recommended: one shared occurrence per assignment scope, atomically claimed by
   one snapshotted eligible recipient; the claimant owns its draft/submission.
2. Alternative: one occurrence per eligible recipient, independently completed.

Use one occurrence per assignment scope, atomically claimed by one eligible member.
Only its claimant owns the associated draft and may complete the task. A group
snapshot never allows peers or managers to read another person's private draft.
Live execution permission is required on every action. Eligible recipients are
snapshotted at materialization; newly added members do not silently inherit old work.
Team/department and scoped-role authority is rechecked live for execution, so a
removed member cannot retain claim/write authority through an old snapshot alone.

## Execution design
Use a bounded RFC 5545 recurrence profile (DAILY/WEEKLY/MONTHLY/YEARLY,
INTERVAL, COUNT/UNTIL, BYDAY, BYMONTHDAY, BYMONTH and WKST=MO). Reject other
parts explicitly. Skip nonexistent local times and invalid dates; choose the first
instant for repeated local times. Fixed intervals use elapsed UTC seconds. Each
materialization window is at most 60 days and 2000 timestamps; definitions cannot
start more than ten years before the window. No unbounded expansion executes.
Calendar presets compile to the same validated rule. Shift recurrence pins a
versioned roster/timezone definition. Milestone and relative-event schedules use
typed, audited tenant-scoped trigger records; no user-authored executable code.
Activation previews pin exact published form versions and assignment targets.
Changes activate a new immutable version and supersede only unclaimed future work;
claimed and submitted work retain the original version and ownership.
Overdue is a time-derived view of unfinished work, not a destructive lifecycle
transition. Workflow-only statuses are reserved for Phase 5 trusted interfaces.
Reminders are durable idempotent in-app records, reauthorized when read. Phase 4
provides an explicit tenant-scoped periodic CLI using a persisted tenant identity;
Phase 6 selects the queue framework and delivers email through typed handoffs.
Schedule managers are explicit workspace admins/owners or project managers and
inherited organization admins. Contributors execute eligible tasks; viewers only
read scoped metadata. Group assignment never grants project access.

Recurrence reference: https://www.rfc-editor.org/rfc/rfc5545#section-3.3.10

## Required constraints for either option
- Membership/assignment is not a permission grant. Recipients must already hold
  effective execution access in the exact tenant/workspace/project scope.
- Retain assignment snapshots; recheck live identity, scope and execution permissions
  for claiming, writes and downloads. Revocation preserves historical authorship.
- Published/active schedule behavior is versioned. Pin an exact published form
  version; never silently follow the latest version or change historical tasks.
- Materialization is bounded, rolling-horizon and database-idempotent under retries
  and concurrent runs. Tenant context and immutable audit accompany operational writes.
- Persist timezone-aware UTC timestamps and schedule timezone metadata. Document
  and test DST gap/overlap behavior before activation.
- Keep generic shift, milestone and event inputs in Core; industry semantics belong
  to Domain Packs. Cross-module reads use typed application interfaces.
- Submitted does not mean approved. Workflow decisions belong to Phase 5;
  notification delivery/worker framework selection belong to Phase 6 ADRs.
- Preserve populated history through guarded downgrade or documented backup/restore
  and reconciliation. Never delete records to force migration rollback.

## Sources
docs/03,05-11,17-22,25-28; ADR-0006 through ADR-0008; AGENTS.md stop conditions.
