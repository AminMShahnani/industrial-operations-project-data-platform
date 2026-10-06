# Phase 6 automation operations

Status: delegated ledger checkpoint; no Phase 6 acceptance or worker rollout.

## Current setup
`uv sync --frozen` installs the ADR-0011 Dramatiq/Redis transport. Broker messages
contain organization/delivery UUIDs only. PostgreSQL migration `8323b0dbac0e`
adds typed outbox delivery, immutable activated rules and retained run evidence.
Source writes now capture supported operational events atomically with their audit.
Action handlers, consumer worker CLI, notifications and email are still being
implemented. Do not launch production workers against this checkpoint.

Run unit/boundary tests with `uv run pytest backend/tests/test_phase6_reliability.py
backend/tests/test_boundaries.py`. The real Redis transport test additionally needs
`IOP_TEST_DATABASE_URL` and the existing development Compose services. Its cleanup
is restricted to a uniquely generated fixture namespace.

## Migration and rollback
Upgrade using `uv run alembic upgrade head`, then `uv run alembic check`. The
new tables have composite tenant keys, immutable event/attempt/receipt triggers,
activated-version transition guards and run source/delegation binding checks.
No existing row is rewritten or deleted by this migration.

An empty database can downgrade to `71db385e7a02`; populated downgrade refuses
before any table is dropped. Source writes may immediately populate event evidence
even before worker rollout. Preserve that history. For populated rollback, stop
writes, back up PostgreSQL and use a forward reconciliation migration or restore
the complete verified pre-upgrade snapshot with an explicit write-replay plan.
Never disable triggers or delete event/run evidence to force a downgrade. An
application rollback must account for pending source events before restarting writes.

## Authority, replay and retries
Q-006 is resolved: the activating organization administrator delegates the exact
reviewed rule content and scope. Each run/replay checks their active identity,
organization administrator authority and current scoped permissions. A platform
operator cannot use this as a tenant bypass. Draft management by a workspace
administrator does not permit activation. Rule retirement stops new matches but
preserves captured pinned runs; revoked delegation prevents their effects.

The application replay service requires fresh requesting-actor scope permission,
fresh delegation and a reason. It retains prior attempts/receipts; it never resets
history. Automatic backoff stops by attempt eight and the total retained attempt
bound is twenty. A publish/commit crash republishes the same scoped IDs. External
effects must use their own durable intents and bounded adapters before rollout.
The integration tests use a typed executor fixture; no public replay endpoint or
production action worker is exposed yet.

## Remaining rollout requirements
Complete scoped consumer/action handlers, bounded backoff/dead letters,
audited replay API/UI and fresh recipient/target access. Redis does not own business
success or durable retry evidence. Notification/email and invitation adapters must
preserve private data and credentials; SMTP uncertainty must not silently resend.
TD-005 orphan reconciliation requires explicit grace, file-owned reference checks
and audited idempotent cleanup. Document guarded migration rollback before rollout.
