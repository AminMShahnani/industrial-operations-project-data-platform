# ADR-0015: Automatic in-app notification delivery

Date: 2026-10-06
Status: Accepted implementation policy within the existing scoped source authority

## Decision

Automatic notices are a fixed, industry-neutral projection of committed operational
sources, distinct from administrator-delegated automation actions. The notification
consumer receives only tenant/delivery UUIDs, locks the delivery, and obtains its
immutable event through an automation application interface. No administrator or
triggering user's privileges are inherited. Recipient contexts are used only for
fresh eligibility checks; creation/skip/attempt audits identify a system actor.

Task creation, due/overdue and reminder sources use the original assignment snapshot
and current task execution eligibility. Workflow assigned steps use the exact captured
visit and current independent assignment policy. Task deliveries also skip work
that is no longer open, in progress or returned, preserving already delivered history.
Task notice reads retain fresh original assignment/group/role permissions but do not
apply operational write lifecycle checks. Closing a project therefore preserves
authorized notice/read history; delivery to a closed project is audited as skipped.
Notify nodes use their existing
immutable notification intent plus current eligibility against the pinned node.
Notification eligibility never grants workflow voting or submission content access.
Only recipients present in the captured event and owning source snapshot can receive
a notice. New group members never inherit old assignments. Each delivery is bounded
to 1,000 captured recipients. No data values, filenames, email addresses or secrets
are copied. Fixed topics distinguish assignments, review requests and other notices.

Revoked/inactive/inaccessible recipients are audited as skipped and do not prevent
other eligible recipients receiving work. A completed delivery is terminal: restoring
access does not backfill a skipped notice. Source access and exact visit eligibility
are checked again on every inbox/detail/read request. Retained evidence is preserved.

All notice/skip effects run inside one database savepoint; transient failure rolls
them back before durable retry evidence is recorded. Automatic exponential backoff
stops after eight attempts, with a twenty-attempt overall limit reserved for controlled
replay. Duplicate/crash redelivery uses event + recipient identities, unique constraints
and the locked terminal delivery state. Unsupported event types complete without an
audience; they cannot silently fan out. The existing Dramatiq actor routes consumers
by the persisted delivery type and dispatcher filters consumer before pagination.

## Migration and compatibility

Migration a5fa16a227ff adds immutable attempt evidence and additive notice origin/
source-intent metadata; pre-existing notices retain automation origin, exact IDs,
source links, run/position bindings and audit/read history. New automatic notices
have no rule run or action position. Separate insert guards enforce both profiles,
including exact source, original recipients and creation audit. Empty rollback is
reversible; populated automatic attempts/notices or new source types refuse rollback
before dropping evidence. Restore/reconcile in a separate environment if necessary.

Future workflow notify nodes and task reminders enter the outbox atomically with
their existing immutable intents/audits. Existing task/review outbox backlog is eligible
for delivery under fresh checks. Pre-outbox historical notify/reminder handoffs are
preserved; an explicit bounded audited reconciliation is required before Phase 6
acceptance rather than silently inventing or rewriting historical events.

Email/invitations, controlled notification replay/reconciliation UI, remaining action
handlers, rule/run UI and telemetry remain Phase 6 work. This does not accept Phase 6
or move any requirement into Phase 7.
