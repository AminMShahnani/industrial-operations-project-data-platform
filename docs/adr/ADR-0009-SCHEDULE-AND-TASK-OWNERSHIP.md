# ADR-0009: Schedule materialization and task ownership

Status: Proposed - Q-004 pending
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

## Pending decision
Q-004 asks the user to select:
1. Recommended: one shared occurrence per assignment scope, atomically claimed by
   one snapshotted eligible recipient; the claimant owns its draft/submission.
2. Alternative: one occurrence per eligible recipient, independently completed.

Neither option is accepted or implemented yet. Record the user's selection here
before implementing assignment-dependent schema and commands.

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
