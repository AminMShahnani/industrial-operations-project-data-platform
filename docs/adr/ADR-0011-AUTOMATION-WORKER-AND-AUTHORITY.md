# ADR-0011: Automation worker and execution authority

Date: 2026-10-06
Status: Worker architecture accepted; execution authority proposed pending Q-006

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

## Proposed execution authority (not accepted)
The activating administrator delegates a bounded action allowlist for the exact
organization/workspace/project. Every execution rechecks their active identity and
current permissions plus target and recipient policies. Revocation stops future
effects; records retain activator, triggering actor, executor and correlation.
Rules cannot approve records, bypass submission ownership, expand access or execute
user code. A dedicated tenant service identity with explicit grants is the alternative.

Q-006 must be resolved before implementing dependent automated writes. AGENTS.md:
"Stop and document instead of guessing when: a security-sensitive requirement is ambiguous".

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
