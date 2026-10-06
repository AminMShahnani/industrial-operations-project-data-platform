# ADR-0018: Historical notification handoff reconciliation

Date: 2026-10-06
Status: Accepted implementation policy within existing source/administrator authority

## Decision

Retained workflow notify intents and task reminder rows are authoritative notification
intents even when created before their outbox adapter existed. A trusted operator with
fresh organization.manage and scoped automation.manage permissions may preview/apply
one page of at most 100 intents in a named workspace and source family. The page is
ordered by immutable intent UUID with an explicit cursor; existing handoffs remain in
the page and are reported without requeueing. A reviewed SHA-256 covers exact original
source snapshots and current handoff identities. Apply requires a reason and rejects
changed previews; tenant-first locking serializes concurrent source writes and apply.

Missing handoffs create a new event and notification-only delivery, atomically with
an immutable operator audit. Event ID is the original intent ID, making repeated and
crash recovery application idempotent. occurred_at and actor identify reconciliation
now, never an invented historical actor/time. The audit retains original created_at
and exact intent/source IDs; task events retain the original scheduled deadline.
No old intent, task, workflow, audit or read history is rewritten. No reminder-to-old-
audit association is inferred. Existing workflow handoffs are found by exact original
intent aggregate ID; existing task reminder handoffs require exact reminder ID. An
ambiguous or mismatched source/delivery fails closed instead of guessing.

Only original captured recipients enter the event. The normal worker rechecks current
source/assignment eligibility, records revoked/obsolete skips and produces minimal
notices. Operator privileges are never delegated to recipients. New group members do
not receive old intents. Completed/skipped-recipient deliveries are not revived;
failed existing deliveries use controlled replay (ADR-0016). Reconciliation does not
activate or run automation rules, send email, or directly publish Redis messages.

## Migration and operations

Migration 34e34c3ce85a adds indexes for bounded workspace intent scans and exact
workflow event lookup. It is reversible even with retained evidence: downgrade drops
only indexes, never data. Existing event/notice/delivery types and guards remain valid.
Rolling back code requires pausing dispatch while switching compatible worker versions;
retain newly captured evidence and resume notification dispatch after verification.
Any application rollback must retain a reader compatible with the new optional
audit `source_created_at` field; older strict audit DTOs cannot parse that evidence.
Revert behavior through a compatible forward patch, never strip retained audit fields.

The command is explicit operational recovery, not an automatic startup backfill.
Run preview/apply separately for each source family and cursor page; no tenant-wide
unbounded scan or implicit privilege bypass. Preview exposes counts/IDs/timestamps,
not recipient lists, form values or email addresses. Verify transaction rollback,
existing handoff preservation, live revocation, pagination and committed duplicate
apply before acceptance. Management API/UI, email/invitations, remaining handlers
and telemetry stay in Phase 6. This does not accept Phase 6 or advance to Phase 7.
