# ADR-0011: Automation worker and execution authority

Date: 2026-10-06
Status: Accepted; user selected the recommended authority on 2026-10-06

## Requirements
docs/12 requires immutable rule versions, safe conditions/actions, idempotent runs,
bounded retries and dead letters. docs/19 requires an atomic transactional outbox.
docs/20 requires fresh server authorization and tenant-scoped secrets. Background
workers must not bypass governed workflow approval, field visibility or project rules.

## Worker decision
Standardize on Dramatiq with Redis. Its synchronous actors fit the existing
synchronous application services and SQLAlchemy transactions. Celery is a larger
alternative; Arq requires asynchronous orchestration around this synchronous stack.
Keep business logic behind typed application ports, independently of broker APIs.
Dramatiq explicitly requires idempotent actors and may deliver messages repeatedly:
https://dramatiq.io/best_practices.html
https://dramatiq.io/guide.html

PostgreSQL owns immutable event intents, consumer deduplication, action receipts,
run attempts and retry/dead-letter state. Redis carries scoped IDs only, never
form payloads, credentials or invitation tokens. Dispatch can repeat after crashes;
broker acknowledgement never constitutes successful business processing. Bound
attempts, network timeouts, batches and event causation depth; expose audited replay.

## Accepted execution authority
The activating administrator delegates a bounded action allowlist for the exact
organization/workspace/project. Every execution rechecks their active identity and
current permissions plus target and recipient policies. Revocation stops future
effects; records retain activator, triggering actor, executor and correlation.
Rules cannot approve records, bypass submission ownership, expand access or execute
user code. No implicit tenant service administrator or authority inherited from the
triggering user is introduced.

Q-006 resolved: user instructed "Do your recommendation" on 2026-10-06. Rule
activation records the delegating organization administrator and exact approved
action content. Every retry/replay rechecks that delegation; authority is never a
cached role snapshot. Retiring a rule stops new event matches, while retained runs
continue only if their pinned delegation still passes fresh checks.

## Delivery and retention
In-app notifications can be transactionally deduplicated. SMTP cannot guarantee
exactly-once delivery after an uncertain acknowledgement; persist delivery attempts
and stable Message-ID, classify uncertain outcomes and require controlled replay.
Consumer deduplication IDs are deterministic UUIDv5 of immutable event ID and
consumer; chronological paging must use persisted timestamps and a tie-breaker.
Email carries minimal scoped notices, with fresh authorization before disclosure.
Do not silently resend invitation bearer secrets or store them in plaintext outbox.
Every migration protects retained operational evidence and documents populated rollback.
TD-005 reconciliation must distinguish referenced private objects from inaccessible
orphans, use an explicit grace period and audit cleanup through file-owned ports.

## Atomic matching and execution evidence
Capture matching activated rule versions in the source transaction, rather than
matching when a delayed worker receives the event. Lock matching versions for shared
read until capture commits, so retirement cannot race creation of their runs.
Activation never backfills old events. Workspace rules match workspace events;
project rules match their exact project, without implicit descendant fanout.

Source audits contain typed IDs and exact form pins, never form values. The
composition root routes supported source audits through the transactional event
bus. Outbox identity/envelope, run source/delegator bindings and activated version
transitions have PostgreSQL guards. Attempts and receipts cannot be updated,
deleted or truncated. Populated rollback refuses before dropping any evidence.

Runs retain their original triggering actor and current delegated executor;
caused events carry the pinned version in a bounded non-repeating causation path.
Rule retirement stops new captures while previously captured runs retain their
version. Every execution and replay rechecks the active delegator's organization
administrator authority and current scope permissions. Replay also requires the
requesting actor's current management permission and an audit reason.
Automatic backoff stops by attempt eight; controlled replay retains all attempts
and refuses at the overall twenty-attempt bound. A broker publish followed by a
transaction crash may republish the same scoped delivery ID; receipts and terminal
run state, not Redis acknowledgement, determine completed work.

## Application action and consumer boundaries
Controlled metadata initially means the existing project description field; it
cannot change lifecycle, grants, memberships or governed submissions. Related
records use the owning master-data service, immutable type schema and exact rule
scope. Form tasks pin a published form version and retain current eligible
assignment snapshots. One action creates a one-time schedule as the audited
materialization batch; its receipt points to that schedule, with resulting tasks
retaining its exact version. Due dates derive from immutable source-event time,
not retry time. Generic tasks without a form remain a distinct pending handler;
they are never silently converted into form tasks.

Starting a workflow explicitly pins workflow ID and version number. Execution
requires that exact version still be active and match the submitted form snapshot.
An existing instance with that pin is returned idempotently; another binding
conflicts. This action never casts votes or bypasses independent approval. Safe
condition lookups use the source's currently authorized public scalar fields;
an administrator cannot read another owner's private draft through automation.

Consumer orchestration locks the scoped delivery and executes each run inside a
database savepoint. Failure rolls back all actions, receipts, audits and caused
events from that attempt, then records bounded failure evidence outside its
savepoint. Different runs can succeed independently. Dispatcher queries filter
their configured consumer in PostgreSQL before pagination, so pending notification
intents cannot starve automation dispatch. Production adapters enqueue durable
external intents rather than doing network effects inside these savepoints.
Database errors are classified without retaining SQL parameters or exception chains
in worker logs. A lost database connection rolls back the delivery transaction;
durable dispatcher redelivery can recover it.

Workflow pin compatibility preflight on development, isolated test and retained
browser databases found zero stored start-workflow actions without a version
number. Previous checkpoints had no production workflow handler or public rule
API. This adds a required action contract without rewriting any immutable version.
If an external pre-rollout installation contains an unpinned action, preserve it
and create/review a new pinned version; never infer a historical target silently.
