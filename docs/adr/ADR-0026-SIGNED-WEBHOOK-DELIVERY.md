# ADR-0026: Signed webhook delivery

Date: 2026-10-10
Status: Accepted (2026-10-10); user selected the documented recommendation with "do".

## Context

docs/16 requires scoped webhook subscriptions, signed payloads, retries, delivery
logs and idempotency IDs. docs/20 requires externally managed secrets and tests for
webhook replay and tenant breakout. ADR-0011 requires fresh delegated authority,
bounded retries and external effects outside the automation transaction. The current
call_webhook action has an endpoint ID, but Core has no endpoint registry, secret
provisioning, outbound address policy, payload disclosure contract or delivery
ledger. Registrable destination and exact data leaving a tenant are security
boundaries; do not infer them from the action identifier.

## Decision

Register immutable organization/workspace/project-scoped endpoint versions under
integration.manage. Bind each activated action to an exact endpoint version and
require the endpoint scope to equal the rule scope. Changing URL, secret reference,
or allowed payload creates a new version; active rule versions are never retargeted.
Endpoint writes require an audited command; no URL or secret changes through rule
JSON.

V1 payloads contain only a fixed, typed event envelope of identifiers, event type,
timestamp, causation and correlation metadata. Do not send form values or raw event
payloads. Sign the exact bounded canonical body using HMAC-SHA256; include the stable
delivery UUID, signing key version and timestamp in headers. Receiver retries use
that same delivery UUID so consumers can deduplicate. Key bytes live in an external
tenant-scoped secret manager, never PostgreSQL, Redis, audit records or logs. The
database holds only an opaque secret reference.

Allow HTTPS only; disable redirects; cap body, connection and response time. Resolve
and validate addresses on every delivery, block loopback/link-local/metadata and
unapproved private ranges, and pin the validated destination for that connection.
Private industrial endpoints require a deployment administrator's explicit egress
CIDR allowlist. Never trust a tenant-provided hostname or redirect as the egress
policy. The deployment network must enforce the same outbound policy. V1 sends the
fixed identifiers-only envelope; selected scalar fields are excluded.

Commit a durable immutable webhook intent inside the automation action savepoint.
Deliver outside that transaction with a separate bounded worker, immutable attempts,
stable delivery UUID, exponential retry and at most eight automatic attempts. A
timeout after sending may be uncertain; do not claim exactly-once. Retain outcome
and permit reviewed, reasoned replay under current delegated authority, with a
twenty-attempt lifetime cap. Keep payload/body/secret out of queue messages and
operator evidence. Metrics use bounded outcome labels, never arbitrary URLs.

## Resolved choices

Q-009 accepts controlled egress, including only deployment-allowlisted private
CIDRs, and the fixed identifiers-only event envelope. Keep outbound delivery
fail-closed until a runtime provides an external secret resolver and pinned-address
transport. This does not change the tag/flag decision.

## Verification after resolution

Test version pinning, endpoint/rule scope, revocation, signing vectors, secret
redaction, DNS rebinding, private/metadata/redirect blocks, stable retries,
uncertain outcomes, duplicate dispatch, reviewed replay/caps, atomic intent
rollback, tenant isolation and populated rollback guards. Use fake transports or a
loopback sink only; never post test payloads to a customer endpoint. Current
foundation verification: five focused tests cover payload exclusion, HMAC signing,
URL checks and address policy. They do not verify a pinned HTTPS transport; outbound
delivery remains unavailable until that requirement is implemented.
