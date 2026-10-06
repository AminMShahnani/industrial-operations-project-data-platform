# ADR-0014: In-app automation notice privacy and delivery

Date: 2026-10-06
Status: Accepted implementation policy within ADR-0011 delegated authority

## Decision

The notifications module owns immutable, minimal notices and immutable read
receipts. An in-app automation action delivers inside the existing run transaction,
without an external effect. Its deterministic identity is run + action position +
recipient; run locking, database uniqueness and transactional receipts prevent
duplicate effects. A failed recipient check rolls back the entire action/run.
This implements one action family; it does not consume automatic task/workflow
notification deliveries or claim email support.

Recipients must be active tenant members with current scope access at activation
and execution. Before delivery and every inbox/read operation, the source-owning
application service checks access again. A notice grants no permissions. Task
notices require the original assignment snapshot and current execution eligibility,
including live team/department/role checks. Workflow notices use fresh participant
or manager access. Submission drafts remain private to their owner, including
against administrators. Project notices require current project read access.

Only explicit configured recipients receive automation notices. No ambient
workspace audience or new group member inherits a captured task assignment.
Supported source links are task, workflow, submission and project. Task links take
precedence over workflow/submission links so another claimant's draft ID is never
copied into a notice. Unsupported sources/channels fail closed with durable run
failure evidence. Task/review topics require matching source kinds; generic notices
use a fixed rule-notice topic. Notices contain no form values, names, filenames,
email addresses, bodies, invitation tokens or user-authored templates.

Inbox queries constrain tenant/workspace/recipient before paging. An administrator
cannot browse another recipient's notices. Revoked sources are omitted without
discarding retained evidence; page continuation advances over invisible rows.
Paging orders persisted creation timestamp plus UUID tie-breaker. The cursor UUID
resolves only within that same recipient/workspace query, rather than treating a
deterministic UUIDv5 as chronological. A repeated read returns the original receipt;
locking serializes concurrent reads and avoids repeated audit effects.

## Persistence and rollback

Migration 73eddd554d17 adds two tables. Composite tenant keys, exact immutable
run/event/action/source evidence guards, append-only triggers and audited creation/
read checks protect retained history. Empty downgrade is reversible. Populated
downgrade refuses before dropping anything: restore a verified backup to a separate
environment and reconcile retained evidence if application rollback is required.
No existing data is rewritten. Authorization remains an application-service check,
not a database privilege bypass.

Scoped typed inbox/detail/read HTTP endpoints and the workspace notification UI
implement this profile. The UI refreshes/paginates current authorized notices and
marks them read; it clears displayed notices after a failed read access check.
Email, invitations, automatic task/workflow intents and queue telemetry remain
required current Phase 6 work. They are not deferred to Phase 7.
