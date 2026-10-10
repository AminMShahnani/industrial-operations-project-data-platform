# ADR-0023: Organization-scoped email evidence and recovery

Date: 2026-10-10
Status: Accepted implementation of ADR-0020 within Phase 6

Expose the notifications-owned email ledger to current organization.manage callers
for the selected organization. This uses existing email queue/replay authority;
workspace managers and recipients do not gain access to other users' delivery
evidence. Email intents already have organization scope, including invitations;
do not infer or backfill workspace/project ownership from changing source data.

Inspection returns only persisted source/recipient/operator IDs, correlation,
timestamps, sanitized state/error codes and bounded immutable attempts. It never
renders SMTP content, addresses, invitation credentials or secret configuration.
Evidence remains inspectable when its source expires or original authority is
revoked, so administrators can diagnose failures. Replay retains the existing
fresh original delegation and source eligibility checks; inspection grants no
source access or permission to send.

Pages filter organization and optional state in SQL before limiting to 100 items.
Order by creation time and ID: delivery IDs are deterministic UUIDv5, so UUID order
alone is not chronological. The cursor resolves an immutable delivery inside the
same organization, then uses its (created_at, id) boundary. Add reversible
organization/time and organization/state/time indexes without rewriting evidence.

Public recovery previews the exact locked delivery, then applies the reviewed hash
and a bounded nonblank reason. Uncertain outcomes also require explicit duplicate
delivery acknowledgement: SMTP acceptance/connection loss cannot prove mailbox
delivery, and replay may send a duplicate. Sending claims are never replayed by
the UI; the existing worker records expired claims as uncertain. Preserve the
eight automatic/twenty lifetime attempt limits and terminal sent/skipped states.
No API queues new email, sends SMTP, rotates secrets, enables tenant-wide opt-in
or dispatches background work. Tests use fake transports or loopback sinks only.
