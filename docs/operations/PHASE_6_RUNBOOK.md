# Phase 6 automation operations

Status: authorized action/consumer increment; no Phase 6 acceptance or production rollout.

## Current setup
`uv sync --frozen` installs the ADR-0011 Dramatiq/Redis transport. Broker messages
contain organization/delivery UUIDs only. PostgreSQL migration `8323b0dbac0e`
adds typed outbox delivery, immutable activated rules and retained run evidence.
Source writes now capture supported operational events atomically with their audit.
Metadata/related-record/form-task/pinned-workflow handlers and the automation
consumer are implemented. Generic tasks without forms, tags/flags, webhooks,
email/invitations remain incomplete. In-app automation notices and automatic task/
workflow consumers with the typed inbox are implemented (ADRs 0014/0015).
Historical pre-outbox handoff reconciliation and controlled notification replay
remain current Phase 6 work. Do not roll out production workers
before the complete Phase 6 acceptance gates pass. Periodic timer/deadline generation
and private-storage reconciliation are now implemented; see their sections below.

## In-app automation notices

Migration `73eddd554d17` adds immutable notices and read receipts. Configure a
`notify` action with explicit active recipient UUIDs and `channels: ["in_app"]`.
Rule administration currently uses the typed application service; its HTTP/UI is
remaining Phase 6 work. Activation/execution recheck recipients and source access;
unsupported email channels and timer/integration/master-data notice sources fail
closed. Task, workflow, submission and project source links use their owning
services. Task notices never disclose another claimant's private draft link.

The automation worker delivers these notices transactionally with run receipts.
The automatic `notifications` consumer now projects fixed task/workflow sources
through the same worker, separately from explicit automation action notices.
Selecting a workspace shows the personal Notifications inbox. Refresh/paging and
mark-as-read use the scoped `/notifications`, `/notifications/{id}` and
`/notifications/{id}/read` endpoints; all require authenticated recipient access.
Revoked source access hides retained notices. Read writes are serialized and
audited once. No form values, arbitrary bodies or invitation secrets are stored.

Empty migration rollback to `a39df7b251c0` is reversible. Once notices or read
receipts exist, downgrade refuses before deletion. Preserve a verified backup and
restore to a separate environment for reconciliation; never remove immutable
evidence to force an application rollback. No existing artifact is rewritten.

## Automatic source notices

Migration `a5fa16a227ff` adds immutable delivery attempts and additive notice
origin/source-intent metadata. Existing automation notices retain their IDs, exact
run/action bindings and read/audit history. Automatic notices use event/recipient
identities, original recipient snapshots and fixed topics, without rule runs.
Task assigned/due/overdue/reminder and workflow review/notify sources are supported.
Reminders and notify nodes now enter the outbox atomically with their existing intents.

Use the existing worker command. Dispatch a bounded batch with:
`uv run python scripts/automation_tick.py --organization <uuid> --subject <trusted-subject> --consumer notifications`.
This previews by default; `--apply` enqueues the filtered batch. The trusted
operator still needs organization management permission. The worker gets no
operator/admin privileges: every recipient is checked against its owning source.
Run the dispatcher periodically so retained retry/dispatched deliveries recover
after broker or process failure. PostgreSQL owns attempt/completion evidence.

Revoked/inactive recipients and obsolete work are audited as skipped. Other
eligible recipients still receive notices. New group members cannot inherit old
events. Completed deliveries are terminal even if skipped recipients regain access.
Source/visit eligibility is rechecked on inbox/detail/read; closed projects preserve
authorized notice history while delivery to closed projects is skipped.
Transient errors roll back all effects and use exponential backoff, stopping by
attempt eight. Permanent errors dead-letter immediately. Attempt codes omit SQL
parameters, data values and secrets. Unsupported source types complete without an audience.

Existing task/review outbox backlog can be dispatched under current checks.
Pre-outbox historical notify/reminder intents can be recovered through the reviewed
reconciliation command below. Do not rewrite old audits or infer a reminder-to-audit
mapping. Email/invitations and complete
queue telemetry are still Phase 6 work.

Empty rollback to `73eddd554d17` is reversible. Populated automatic notices,
attempts or new notify/reminder source types refuse downgrade before evidence loss.
Restore a verified backup to a separate environment and reconcile if needed.

Run unit/boundary tests with `uv run pytest backend/tests/test_phase6_reliability.py
backend/tests/test_boundaries.py`. The real Redis transport test additionally needs
`IOP_TEST_DATABASE_URL` and the existing development Compose services. Its cleanup
is restricted to a uniquely generated fixture namespace.

## Historical notification handoff reconciliation

Migration `34e34c3ce85a` adds scoped cursor/aggregate lookup indexes. It changes no
stored record and can be downgraded with populated history because only indexes drop.
Preview one page using:
`uv run python scripts/notification_reconcile.py --organization <uuid> --workspace <uuid> --kind task_reminder --subject <trusted-subject>`.
Repeat separately with `--kind workflow_notify`. A configured trusted issuer,
organization.manage and scoped automation.manage are required; platform authority
alone does not bypass tenant permissions. Preview exposes IDs, timestamps and
recipient counts, never recipient lists or submitted values. At most 100 intents
are reviewed per call. Use the returned `cursor` as `--after <cursor>` for the next
page. Existing handoffs remain visible with `existing_event_id` and are not changed.

Review missing intents and apply the same page with
`--apply --review-sha256 <review-hash> --reason "Reviewed historical recovery"`.
Changed snapshots/capture state fail with `notification_handoff_review_required`;
preview again. A stale repeated apply cannot duplicate a handoff. All captures and
audits commit together; dependency failure rolls the page back. Restart the same
page after a crash to inspect retained capture identities before applying again.

Events use original intent IDs and captured recipients but current reconciliation
time/operator. `notification.handoff.reconciled` retains original creation time and
source binding. Old reminder audits need no guessed row association. Notify lookup
uses exact intent aggregate IDs; mismatched/ambiguous source or missing delivery
evidence fails closed. No automation rules run. Dispatch the notification-only
deliveries with the existing notification dispatcher; the command does not publish
Redis messages or deliver email. Workers recheck current access and skip obsolete
work. Existing failed deliveries use replay below; completed skips are not backfilled.

Application rollback: pause dispatch while switching compatible code, preserve all
new audit/event/delivery evidence, and resume with a worker that supports the existing
task.reminder.created/workflow.notification.requested types and the optional audit
`source_created_at` field. Older strict audit DTOs require a compatible forward patch;
never remove fields from retained audit evidence. Index downgrade is
reversible independently. No production rollout is implied (ADR-0018).

## Controlled notification replay

Preview one failed delivery without writing or enqueueing:
`uv run python scripts/notification_replay.py --organization <uuid> --workspace <uuid> --delivery <uuid> --subject <trusted-subject>`.
The configured trusted issuer and operator must retain organization.manage and
scoped automation.manage permissions. The command outputs a typed delivery review
and `review_sha256`, containing scoped IDs and bounded status metadata, no recipient
list or form values. This is a trusted host command, not an HTTP authentication path.

After reviewing the failure and repairing its cause, run the same command with
`--apply --review-sha256 <review-hash> --reason "Reviewed repair reason"`.
Apply locks and compares the current delivery to the preview; stale previews fail
with `notification_replay_review_required`. Only retry/dead-letter deliveries below
twenty total attempts qualify. Pending/dispatched/completed deliveries cannot replay.
Apply atomically records `outbox.notification.replayed` and makes the same delivery
due now. It does not publish to Redis; the notification dispatcher above does that.

Replay preserves source event, original recipients, notice/read evidence and attempt
numbers. The worker rechecks live source/recipient access. Completed skipped deliveries
cannot backfill recipients when access is restored. Attempts beyond the automatic
eight-attempt window require another reviewed manual replay after failure. Duplicate
apply requests using the same preview produce one requeue and audit, with stale
conflicts for the others. Historical pre-outbox reconciliation and management API/UI
remain Phase 6 work (ADR-0016).

No new schema migration. For an application rollback, pause dispatch, retain all
queued deliveries and immutable replay evidence, and resume with a compatible worker.

Tenant identity checks and workers use organization-before-user/delivery/run locking
(ADR-0017). Keep transactions bounded; the existing tenant row lock serializes work
within an organization. Do not bypass these owning application lock interfaces during
replay/dispatch or remove identity locks to work around contention.

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

The dispatcher filters the selected consumer before pagination, defaulting to
`automation`; select `--consumer notifications` for automatic notices.
Unconfigured action families fail closed
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

## Timer and task deadline generation
ADR-0013 defines the bounded detection/catch-up rules. Upgrade to `a39df7b251c0`
using `uv run alembic upgrade head`, then check drift with `uv run alembic check`.
This adds immutable timer occurrence and task deadline evidence without rewriting
existing definitions, tasks, audits or runs. Read-only compatibility preflight found
zero previously stored timer events lacking exact version/slot pins in development,
isolated test and retained browser databases. Never rewrite historical envelopes to
invent missing pins in another pre-rollout installation; preserve them and reconcile
explicitly before enabling its periodic consumer.

Preview one exact timer rule:

```powershell
uv run python scripts/automation_triggers.py timer --organization <UUID> --workspace <UUID> --rule <UUID> --subject <trusted-subject>
```

Add `--apply` to capture at most 100 slots and their pinned runs per invocation.
Output is typed JSON with tenant/workspace, request/correlation IDs and batch counts.
`more=true` means another bounded invocation has overdue slots; `next_at` is the
next cadence slot. Only slots at or after the version's activation are eligible.
Retirement stops generation; activating a new version does not inherit old progress.
Each timer event matches its own exact version. Both operator scope and activating
administrator delegation are rechecked before generation and effects.

Preview task deadlines in one exact workspace or project scope:

```powershell
uv run python scripts/automation_triggers.py deadlines --organization <UUID> --workspace <UUID> --subject <trusted-subject>
```

Use `--project <UUID>` for a project; workspace batches do not fan out into projects.
Add `--apply` to capture the first 100 pending tasks (at most 200 due/overdue events).
`--cursor <UUID>` continues the returned cursor. Start each new periodic scan without
a cursor so skipped locked tasks are revisited. Already captured marks are filtered
before pagination and never generate duplicate events or starve new pending work.
Due is inclusive of the deadline; overdue is strictly after it. Unfinished work is
open/in-progress/returned. These events preserve task state/revision and never read
private draft values. Source audit/outbox/run/marker writes commit atomically.

Invoke scoped batches periodically (for example every 30 seconds), then use the
existing automation dispatcher and worker to process captured runs. Detection time
and original slot/deadline are retained separately. Broker acknowledgment does not
mean effects committed. No background service identity or HTTP bypass is introduced.

An empty periodic migration can downgrade to `8323b0dbac0e`. Populated downgrade
refuses before dropping either table or its guards. Stop generation/dispatch before
rollback, preserve evidence and use a reviewed forward fix or a verified complete
database restore with a write-replay plan. Existing already-captured runs keep their
exact version and fresh delegation checks. Never delete marks/history to force a
downgrade or use a cursor as a permanent completeness watermark.
