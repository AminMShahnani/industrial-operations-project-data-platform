# ADR-0024: Generic task completion authority

Date: 2026-10-10
Status: Accepted; user instructed "do your recommandation" on 2026-10-10

## Context

docs/12 distinguishes create task from create form task. ADR-0011 requires a
distinct generic handler. Existing tasks require schedule/form pins; claiming
creates a private draft. docs/11 does not define completion without a submission.
ADR-0009 limits shared-task completion to its eligible claimant. ADR-0010 requires
independent approval of governed records. Whether generic completion needs review
is a governance-sensitive boundary subject to AGENTS.md's stop condition.

## Accepted decision

One eligible snapshotted recipient atomically claims the shared generic task,
then acknowledges completion under fresh identity, scope, assignment and
task.execute checks. Use a distinct terminal completed state with immutable actor
and timestamp audit. Do not create a submission, approve a record or cast a vote.
Work requiring captured data or independent approval uses form tasks/workflows.

Preserve existing form-task pins, private drafts and transitions. Generic creation
belongs to the task service with typed immutable automation provenance, assignment
snapshots, event-time due dates and database idempotency. Core remains neutral;
industry-specific requirements belong in Domain Packs.

Persist kind, immutable origin_id and completed_at on the owning task aggregate.
Form tasks retain all six exact schedule/form pins; generic tasks have none.
Automation derives origin_id from its pinned run and action position, and derives
each task ID from origin plus assignment key. One action creates one shared task
per distinct assignment; its receipt points to the first task in immutable action
definition order, with all related tasks retaining the same origin. Creation audits
retain delegated run/version/event correlation through the existing event bus.
Due dates use source-event time; display timezone uses organization settings.
Generic tasks reuse deadline/notification ports and have no implicit reminders.

The historical action contract remains readable. Validation/execution explicitly
reject create_task with form pins. Installations retaining that formerly ambiguous
action must review a new create_form_task version, without rewriting the old one.
Preflight found zero such actions in development, isolated test and retained browser
databases. Duplicate generic assignment keys are rejected. Historical definitions
are never silently reinterpreted as generic work.

Migration d318af6c902e defaults existing rows to form, relaxes pin nullability under
an explicit kind constraint and preserves the frozen Phase 5 form-task guard.
Generic guards enforce open creation, claim preservation, completion/cancellation
transitions and immutable history. Downgrade refuses before DDL if any generic task
exists; use verified backup/restore for populated rollback.

Alternative: independent review before completion. That requires a specified
review policy, eligible reviewers and return/resubmission semantics; do not infer
these from a nonexistent form workflow.

Q-008 is resolved by the user's explicit selection. Implementation proceeds with
claimant acknowledgement; independent record approval remains unchanged.

## Verification after resolution

Review typed task-kind/provenance contracts and guarded migration. Preserve all
retained data; refuse destructive populated rollback. Test ownership, revocation,
scope isolation, concurrent claim/completion, duplicate delivery, transactional
recovery, audits, form-task regressions and browser execution. All local and
exact-code hosted gates remain required. Phase 6 is not accepted.

Implementation evidence: all 285 backend/18 frontend tests and local static,
migration, build and contract checks pass. Hosted run 38052949486 passes both jobs
on exact code d25ad7a5e672b2e5d3240b36db8964623a6c7d1d, including real PKCE
execution and committed concurrent worker/claim/completion retries.
