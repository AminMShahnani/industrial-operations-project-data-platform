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
