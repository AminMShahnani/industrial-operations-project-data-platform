# Phase 6 automation operations

## Controlled project tags and flags (ADR-0025)

Use append_tag or append_flag with an exact case-sensitive ASCII value of 1–60
characters (letters, digits, underscore, dot, colon or hyphen). The rule must have
an exact project scope; workspace-only activation fails with
automation_project_annotation_required. Labels are descriptive metadata. Domain
Packs own industry meanings; labels do not change permissions, lifecycle or approval.

The original activating administrator's authority and project.manage permission
are checked at activation and every execution/retry. Terminal projects refuse all
appends, including duplicates. Each project permits 1000 distinct annotations
across both kinds. Repeating the same kind/value returns its original immutable
row and audit; every run/action retains its own receipt pointing to that row.
Case changes and tag versus flag are distinct. Multi-action failure rolls back
annotation creation together with the other effects and receipts.

Authorized project.read users can inspect tags/flags in workspace administration,
filter by kind, refresh and load further pages. GET
/api/v1/organizations/{org}/workspaces/{workspace}/projects/{project}/annotations
returns 100 rows and next_cursor; optional kind=tag|flag filters before paging.
Preserve the exact scope/filter when using the cursor. Foreign, missing or
mismatched-filter cursors fail. Historical reads remain available on terminal
projects under current authorization. There is no public manual append endpoint.

Upgrade to e49b7d83af20 before deployment. It adds project_annotations and an audit
tenant/ID uniqueness constraint without rewriting existing project or audit rows.
Database guards bind inserts to exact creation audits and reject mutation/deletion/
truncation. Downgrade to d318af6c902e locks annotation writes before checking rows,
and refuses populated rollback before DDL. Stop producers/workers before application
rollback and retain compatible read/evidence code. For populated schema rollback,
use a verified backup/restore plan; never delete annotations or audits to force it.

## Generic task acknowledgements (ADR-0024)

Activate a create_task action with name, distinct assignments and due_seconds
(60 seconds to 30 days), without form_id/form_number. Execution creates shared
generic work through the task service under fresh original delegation. Occurrence
and due timestamps derive from the source event, including on retry. Snapshots do
not grow when recipients are added later. Receipt target_id identifies the first
created task; immutable origin_id groups all tasks from that exact run/action.

In My Work, claim generic work then use Acknowledge completion when done. Only
the current eligible claimant can acknowledge it. Completion records actor/time
and a terminal completed state, without a form submission or record approval.
Server-side membership, permission and project lifecycle checks apply every time,
including retries. Completed/cancelled work cannot be reopened. Managers may cancel
pending work with the existing reviewed reason flow but cannot complete for others.
Governed records continue to use create_form_task and independent workflows.

API POST /tasks/{task_id}/start and POST /tasks/{task_id}/complete under the
organization/workspace prefix both accept expected_revision. Exact claimant
completion retries return retained terminal evidence without another audit.
Generic tasks reuse task-created notifications and due/overdue generation; no
reminder policy is implicitly attached. Form tasks refuse the complete endpoint.

Upgrade all databases to d318af6c902e before deploying these contracts. Existing
tasks default to form with exact pins and history preserved. Downgrade to
ba6e379cc281 works with retained form tasks, but refuses before DDL if generic tasks
exist. Disable new writes before rollback; use a verified backup/restore plan when
generic history exists. Never remove evidence to force a downgrade. Retained older
create_task actions with form pins require a reviewed new create_form_task version;
no immutable rule is rewritten automatically.

## Verified-email invitations (ADR-0019)

In workspace administration, choose **Verified email sign-in link**, review the
organization/workspace, email and role, then create the invitation. Share the link
with the intended member. This slice does not send email; the SMTP adapter remains
required Phase 6 work. No bearer token, email, role or credential appears in the
link. The member signs in through the configured OIDC provider and explicitly
chooses **Accept sign-in invitation**. Validated organization/invitation IDs survive
PKCE as application state and are cleared from the URL after acceptance. GET never
accepts an invitation.

Creation: `POST /api/v1/organizations/{org}/invitations/verified-email`, with
`id` (caller-generated UUIDv7 retained for retry), `email`, `role`, `scope_type`
and `scope_id`. The response contains only invitation/organization IDs and expiry.
Retry the exact request with its original ID after a lost response. Reusing an ID
with another target, scope, role, mode or inviter conflicts; every retry checks
current delegation. A deliberate new invitation uses a new ID and seven-day life.

Acceptance: authenticated
`POST /api/v1/organizations/{org}/invitations/verified-email/{id}/accept`, without
a bearer secret or request body. Only the provider's matching verified email is
eligible. Acceptance checks active organization/target workspace, active inviter
and exact current delegation. Used, expired, mismatched or revoked invitations
fail closed. No pending-invitation list or public preview is exposed. Existing
code invitations retain their endpoints and digest-only storage.

Migration `e18c49c4be63` defaults existing invitations to `token`, preserving
digests/timestamps, and adds `verified_email` with no digest. Database guards make
binding fields immutable and acceptance one-way, and prohibit history deletion/
truncation. Empty/token-only downgrade preserves rows. Any verified-email history
causes downgrade to refuse before schema changes. For application rollback, stop
new-mode creation and retain compatible acceptance code. Populated schema rollback
requires a forward fix or verified full backup restore with a write-replay plan.
Never fabricate digests, reset acceptance, extend expiry or remove evidence to
force rollback. SMTP attempts/recovery will follow ADR-0011 in the next slice.

Status: Phase 6 in progress. Verified-email lifecycle passes local and hosted gates
on 82cf4e5 / run 38036138271. SMTP delivery remains pending; no phase acceptance
or production rollout.

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

## Scoped SMTP delivery

ADR-0020 adds an explicit operator queue for a verified-email invitation or one
retained notice. Upgrade to `208f826ca492` and check migration drift. Email is
disabled unless `IOP_EMAIL_PROFILES_DIRECTORY` names an externally mounted secret
directory. Never commit this directory or copy its contents into logs or evidence.
Each `<organization-UUID>.json` contains the same `organization_id`, `host`, `port`,
`sender`, `tls`, `app_origin`, and optional paired `username`/`password`. Production
requires verified STARTTLS and an HTTPS application origin. Cleartext is allowed
only for an unauthenticated loopback test sink. Profiles are read on each attempt.

Preview the exact source as a current organization administrator using the
configured trusted issuer:

```powershell
uv run python scripts/email_operations.py queue --organization <UUID> --subject <trusted-subject> --kind invitation --source <invitation-UUID>
uv run python scripts/email_operations.py queue --organization <UUID> --subject <trusted-subject> --kind notice --source <notice-UUID> --recipient <user-UUID>
```

Add `--apply --reason "Requested email delivery"` to commit the deterministic
delivery ID and queue audit atomically. Repeating this command preserves the same
delivery and attempt history. Addresses and fixed message text are rendered only
at send time through the owning identity/notification services. This queue does
not opt in tenants, capture all future notices, or backfill historical email.
ADR-0021 now supports explicit email channels on newly authored/activated notify
actions. Existing in-app definitions and automatic task/workflow projection remain
unchanged. Queue capture works while SMTP is disabled; configure the tenant profile
and periodically dispatch to send captured intents.

Start the separate worker and preview/dispatch a tenant batch:

```powershell
uv run dramatiq operations.smtp_worker:broker
uv run python scripts/email_operations.py dispatch --organization <UUID> --subject <trusted-subject>
uv run python scripts/email_operations.py dispatch --organization <UUID> --subject <trusted-subject> --apply
```

Dispatch is capped at 100 due IDs, including expired claims. Repeat periodically;
safe retries become due after bounded backoff. Broker envelopes contain only tenant
and delivery UUIDs. Redis acknowledgment is not completion. `sent` records provider
DATA acceptance, not mailbox delivery. No provider configuration consumes an attempt.
Each committed claim has a 90-second lease; the actor has a 60-second limit and SMTP
operations have five-second socket timeouts. Original operator, inviter/recipient,
tenant and source authority are checked under the tenant revocation lock before send.
Lost authority records terminal `skipped` evidence.

A send or commit crash becomes `uncertain` when its claim expires. It never resends
automatically. Review provider evidence before previewing replay:

```powershell
uv run python scripts/email_operations.py replay --organization <UUID> --subject <trusted-subject> --delivery <delivery-UUID>
```

Apply with `--apply --review-sha256 <returned-hash> --reason "Provider evidence reviewed"`.
Stale reviews are rejected. Replays preserve the original source, recipient, operator
and stable Message-ID; a duplicate mail remains possible when the original outcome
was uncertain. Automatic retry stops at eight attempts; controlled replay stops at
twenty total attempts. Accepted/skipped deliveries are terminal. Inspect scoped
`email_deliveries`, immutable `email_attempts`, and `email.*` audits as evidence.

Stop queue/dispatch and the worker to disable sending. Empty tables can downgrade
to `e18c49c4be63`; populated downgrade refuses before removing either ledger.
Preserve evidence and use a forward fix or verified full restore with a write-replay
plan. Never delete attempt/source/audit history to force rollback or redelivery.

## Explicit invitation and rule email capture

Upgrade to `5caef6ad5721` before enabling the new source paths. Existing notices
remain visible with `in_app=true`; their IDs, source bindings and audit/read history
are preserved. The new partial index filters visible notices before inbox paging.

An organization administrator can select **Verified email sign-in link**, check
**Email the sign-in invitation**, and provide an **Email request reason** in the
workspace invitation form. The typed creation API accepts `email_delivery=true`
and `email_reason` with the existing exact invitation UUID. Creation and email
queue/audit commit atomically. Retries produce one invitation and one email intent.
Default `email_delivery=false` preserves manual sharing. A false retry does not
cancel previously queued email. Workspace invitation managers without organization
management authority can create manual invitations but cannot delegate email.
The UI says queued rather than claiming provider/mailbox delivery.

Notify actions accept unique channel lists `["in_app"]`, `["email"]`, or both in
either order. The activating organization administrator delegates those exact
immutable channels and captured recipients. Automation commits minimal notice,
email intent, action receipt and audits together inside its run savepoint. Failure
rolls back the entire attempt. No SMTP or broker publication occurs in that transaction.
Email-only notices remain immutable internal source evidence; inbox/detail/read
and cursor APIs exclude them. Source authorization is still checked when rendering
email. A restored grant does not backfill skipped delivery, and duplicate dispatch
does not reset accepted mail. Use the same scoped SMTP dispatcher and worker above.

This does not introduce tenant-wide opt-in or implicit email for task assignment,
workflow review/notify or reminder projections. Their existing in-app behavior and
historical handoffs remain intact. Configure email on supported task/workflow events
through explicitly activated notify rules. Remaining handlers and telemetry are Phase 6 requirements.

Downgrade to `208f826ca492` is allowed only when no email-channel rule version or
email-only notice exists; the old SQL channel guard and schema are restored. With
retained email channel evidence, rollback refuses before changes. Stop producers,
dispatch and workers, then use a forward fix or verified full restore with a write
replay plan. Never edit immutable versions, notices or attempts to force downgrade.

## Scoped automation administration

Managers open Automation under the selected workspace/project. Create a draft
with the metadata starter (project scope) or a supported declarative definition.
Save changes before previewing activation. Organization administrators review the
saved content/hash and apply activation; editing invalidates the preview. Active
and retired definitions are immutable: clone to an unused positive version number.
Retire with a reason and current rule revision. Captured runs retain their version.

All routes use `/api/v1/organizations/{organization_id}/workspaces/{workspace_id}`
plus `/automation-rules`. Rules and versions page with opaque UUID cursors; runs
are listed at `/{rule_id}/versions/{number}/runs`. Read minimal attempt/receipt
history at `/{rule_id}/runs/{run_id}`; target IDs confer no target access. Every
administration route freshly checks exact scoped automation.manage. Activation
also requires organization.manage. Source form/event payloads are never returned.

For retry/dead-letter recovery, inspect evidence, repair the cause, preview replay
at `/{rule_id}/runs/{run_id}/replay`, then apply with dry_run=false, the exact
review_sha256 and a nonblank reason. Preview changes no evidence. Apply rechecks
original administrator/scope and the exact run plus queue state; stale/duplicate
reviews conflict. Attempts/receipts remain intact and twenty attempts is final.
Replay requeues durable IDs; the existing dispatcher/worker performs the effects.

Rollback: disable the administration UI/routes and deploy the preceding code;
there is no migration or data removal. Retain all newly created rules, immutable
versions, run history and audits. Previously captured runs still need the worker;
retirement stops new matches. ADR-0022 records the boundary.

## Email delivery and recovery console

Organization administrators open Email delivery and recovery for the selected
organization. List all states or filter before chronological paging; timestamps
and delivery UUID together define the cursor because IDs are deterministic UUIDv5.
Inspect original source/operator IDs, correlation, next check and immutable attempts.
The console returns no recipient addresses, SMTP content, invitation credentials or
secret configuration. Sent means SMTP provider acceptance, not mailbox delivery.
Evidence stays visible after source expiry/revocation; replay still requires the
original queue administrator and current source/recipient eligibility.

The organization-level API prefix is
`/api/v1/organizations/{organization_id}/email-deliveries`: GET list with optional
state/cursor, GET `/{delivery_id}` evidence, POST `/{delivery_id}/replay` preview
with dry_run=true. Review the state, resolve the failure, then apply dry_run=false
with review_sha256 and a nonblank reason. Uncertain sends additionally require
acknowledge_uncertain=true after reviewing provider evidence and possible duplicate
mail. A changed state invalidates the review. All attempts remain retained;
sending/sent/skipped deliveries and the twenty-attempt lifetime limit refuse replay.
No API dispatches mail or configures SMTP; the existing scoped dispatcher/worker
processes the requeue. Expired sending claims become uncertain through that worker.

Migration ba6e379cc281 adds organization/time and organization/state/time lookup
indexes only. Upgrade all application databases before enabling the console.
Downgrade to 5caef6ad5721 drops only those indexes, preserving populated deliveries,
attempts and audits. Disable the console/routes before rolling back application
code. Older ledger/source downgrade guards still apply; never delete evidence to
force rollback. Use fake transports/loopback sinks for verification.
