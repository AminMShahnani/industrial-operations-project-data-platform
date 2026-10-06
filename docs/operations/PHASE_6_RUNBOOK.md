# Phase 6 automation operations

Status: foundation checkpoint only; no Phase 6 acceptance or worker rollout.

## Current setup
`uv sync --frozen` installs the ADR-0011 Dramatiq/Redis transport. Broker messages
contain organization/delivery UUIDs only. The PostgreSQL durable outbox/run ledger,
authorized handlers, worker CLI and notifications are not yet deployed. Do not
launch production workers against this checkpoint. Database head remains
`71db385e7a02`; no migration or existing history changed.

Run unit/boundary tests with `uv run pytest backend/tests/test_phase6_reliability.py
backend/tests/test_boundaries.py`. The real Redis transport test additionally needs
`IOP_TEST_DATABASE_URL` and the existing development Compose services. Its cleanup
is restricted to a uniquely generated fixture namespace.

## Remaining rollout requirements
Q-006 must resolve worker authority before governed actions. Require atomic typed
outbox persistence, scoped consumer/action receipts, bounded backoff/dead letters,
audited replay and fresh recipient/target access. Redis does not own business
success or durable retry evidence. Notification/email and invitation adapters must
preserve private data and credentials; SMTP uncertainty must not silently resend.
TD-005 orphan reconciliation requires explicit grace, file-owned reference checks
and audited idempotent cleanup. Document guarded migration rollback before rollout.
