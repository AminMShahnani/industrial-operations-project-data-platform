# ADR-0024: Generic task completion authority

Date: 2026-10-10
Status: Proposed; awaiting Q-008

## Context

docs/12 distinguishes create task from create form task. ADR-0011 requires a
distinct generic handler. Existing tasks require schedule/form pins; claiming
creates a private draft. docs/11 does not define completion without a submission.
ADR-0009 limits shared-task completion to its eligible claimant. ADR-0010 requires
independent approval of governed records. Whether generic completion needs review
is a governance-sensitive boundary subject to AGENTS.md's stop condition.

## Recommended decision (not accepted)

One eligible snapshotted recipient atomically claims the shared generic task,
then acknowledges completion under fresh identity, scope, assignment and
task.execute checks. Use a distinct terminal completed state with immutable actor
and timestamp audit. Do not create a submission, approve a record or cast a vote.
Work requiring captured data or independent approval uses form tasks/workflows.

Preserve existing form-task pins, private drafts and transitions. Generic creation
belongs to the task service with typed immutable automation provenance, assignment
snapshots, event-time due dates and database idempotency. Core remains neutral;
industry-specific requirements belong in Domain Packs.

Alternative: independent review before completion. That requires a specified
review policy, eligible reviewers and return/resubmission semantics; do not infer
these from a nonexistent form workflow.

## Verification after resolution

Review typed task-kind/provenance contracts and guarded migration. Preserve all
retained data; refuse destructive populated rollback. Test ownership, revocation,
scope isolation, concurrent claim/completion, duplicate delivery, transactional
recovery, audits, form-task regressions and browser execution. All local and
exact-code hosted gates remain required. Phase 6 is not accepted.
