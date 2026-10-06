# ADR-0016: Controlled notification replay

Date: 2026-10-06
Status: Accepted implementation policy under existing administrator authority

## Decision

An audited operator command can preview and requeue one notification delivery in
retry or dead-letter state. The operator must retain organization.manage and scoped
automation.manage permissions. Platform administration alone is insufficient. Apply
requires a reason and the SHA-256 of the reviewed delivery state; a locked fresh read
rejects concurrent changes or repeated application of a stale preview. Preview writes
no evidence. This follows the existing operator identity model used by dispatch.

Replay preserves the exact immutable source event, original audience, delivery ID,
correlation, attempts, notices and read history. It does not reset the twenty-attempt
limit or revive completed/skipped-recipient deliveries. It requeues without publishing
to Redis; the normal dispatcher and worker remain responsible for execution. Current
recipient/source eligibility is checked by the worker, never granted by the operator.
Automatic backoff still ends at eight total attempts; subsequent manual attempts need
another explicit review when they fail. An immutable replay audit records the operator,
source, previous state, attempt number and reason in the requeue transaction.

No schema migration is needed: existing delivery identity/counter guards and immutable
audit/attempt records support this transition. Rolling back application code preserves
all replay evidence and queued work; pause dispatch while changing worker versions.

Historical pre-outbox notify/reminder reconciliation remains a separate bounded
provenance-preserving command. No old audit/event is invented or rewritten here.
Scoped management API/UI, email/invitations, other handlers and telemetry remain
Phase 6 work; no phase acceptance or Phase 7 deferral is implied.
