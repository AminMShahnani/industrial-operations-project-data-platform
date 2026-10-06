# Phase 6 automation operations

Status: authorized action/consumer increment; no Phase 6 acceptance or production rollout.

## Current setup
`uv sync --frozen` installs the ADR-0011 Dramatiq/Redis transport. Broker messages
contain organization/delivery UUIDs only. PostgreSQL migration `8323b0dbac0e`
adds typed outbox delivery, immutable activated rules and retained run evidence.
Source writes now capture supported operational events atomically with their audit.
Metadata/related-record/form-task/pinned-workflow handlers and the automation
consumer are implemented. Generic tasks without forms, tags/flags, webhooks,
notifications and email remain incomplete. Do not roll out production workers
before the complete Phase 6 acceptance gates pass.

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
The ledger tests use a typed executor fixture; action tests exercise the real owning
services and actual concurrent Redis worker. No public replay endpoint is exposed yet.

## Automation worker and dispatcher
In development, start the configured actor using:
`uv run dramatiq operations.automation_worker:broker --processes 1 --threads 4`.
The deployment process supplies the existing database/Redis/S3 settings and must
have access to tenant-scoped secrets when external adapters are implemented.
Actor messages contain only organization/delivery UUIDs; malformed IDs and database
errors have stable sanitized errors. Every delivery opens its own database transaction;
per-run savepoints retain successful independent runs while rolling back failed ones.

Preview one bounded dispatcher batch with
`uv run python scripts/automation_tick.py --organization <UUID> --subject <trusted-subject>`.
Add `--apply` to publish up to 100 due automation deliveries. The configured trusted
issuer and current organization-administrator grant are required; this follows the
existing operator CLI trust model and is not an unauthenticated network endpoint.
Invoke periodically (for example every five seconds). Dispatched deliveries are
revisited after 60 seconds if no durable completion was recorded. Run retries use
their persisted next_at/backoff. Redis acknowledgement is not completion evidence.

The dispatcher currently filters `automation` before pagination and does not
dispatch pending `notifications` intents. Unconfigured action families fail closed
during validation. An existing workflow binding is reused only when its exact
version matches; workflows must still receive independent human approval.
Form-task receipts refer to their one-time schedule batch; concrete tasks retain
exact form/schedule versions, original assignment recipients and event-time due dates.

## Remaining rollout requirements
Complete scoped consumer/action handlers, bounded backoff/dead letters,
audited replay API/UI and fresh recipient/target access. Redis does not own business
success or durable retry evidence. Notification/email and invitation adapters must
preserve private data and credentials; SMTP uncertainty must not silently resend.
TD-005 orphan reconciliation is implemented below. Other rollout requirements
remain current-phase work; no production worker rollout is authorized by this checkpoint.

## Private upload orphan reconciliation
ADR-0012 owns the cleanup policy and race/crash boundaries. Preview one bounded
tenant batch using the configured trusted issuer and known current tenant administrator:

```powershell
uv run python scripts/reconcile_storage.py --organization <UUID> --subject <trusted-subject>
```

The default grace is 24 hours; `--grace-hours` accepts 24–720. Inventory is capped at
100 objects, returns counts and `next_cursor`, and does not expose filenames or
contents. Pass a returned cursor using `--cursor` to inspect the next page. Only
canonical upload paths qualify. Every file row remains a reference, including unused
attachments. Unknown paths, referenced files and objects within grace are preserved.

Apply a reviewed batch with `--apply --reason "Reconcile failed-upload objects"`.
The CLI commits immutable requested intents before any deletion and prints their
UUIDs. Each intent uses a separate transaction, fresh tenant authority, the shared
upload lock and fresh reference/age/ETag checks. Busy, changed and referenced objects
remain. Conditional S3 deletion has no unconditional fallback. Audit results record
deleted/missing/referenced/changed/busy/failed; storage failure is resumable.

Retry a retained request with:

```powershell
uv run python scripts/reconcile_storage.py --organization <UUID> --subject <original-subject> --apply --resume <intent-UUID>
```

Resume retains the original scope, ETag, grace, reason and requester. Revoked or
suspended authority denies execution. A delete/DB-commit crash leaves requested
evidence and a later missing outcome; it does not recreate or repeatedly delete
objects. Audit failures stop processing, and pending intent UUIDs remain available
in the requested evidence. Do not infer successful deletion from process exit alone.
The cleanup adapter requires READ COMMITTED and conditional-delete support; other
isolation levels or unsupported storage fail closed. Real storage conformance tests
verify wrong/stale ETags preserve data before testing a matching deletion.

No migration is required and no retained file/audit row is rewritten. Stop the CLI
to disable cleanup. This does not implement attachment retention or version deletion.
Restore any incorrectly removed object from a verified object-store backup while
preserving its original reference and cleanup history.
