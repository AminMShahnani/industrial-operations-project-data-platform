# ADR-0020: Durable scoped SMTP delivery

Date: 2026-10-10
Status: Accepted; implements ADR-0011 and ADR-0019 under the authorized Phase 6 scope

## Decision

Add a notifications-owned email ledger and a separate Dramatiq email actor.
An audited organization administrator explicitly queues one verified-email
invitation or retained in-app notice. Preserve the exact source and recipient;
deduplicate by organization/source/recipient. No implicit historical email backfill
or automatic opt-in is introduced. Rule email channels remain unavailable until
their action/automatic capture integration is implemented in Phase 6.

The original queue administrator delegates that exact email intent. Recheck their
active organization.manage authority on each send/replay. Invitation rendering
uses the identity service's active, unexpired, unused verified-email invitation
and current inviter delegation. Notice rendering uses current recipient identity
and source-owning notice access. Emails contain fixed minimal text and an origin-
owned sign-in link; no form values, invitation secrets, role or email appear in
links. Retain only source IDs in the ledger and broker; render address/content
ephemerally. SMTP profile secrets live outside the repository/database in a mounted
secret directory, one UUID-named file per tenant, with matching embedded tenant ID.
No profile means delivery is disabled. Production requires verified TLS and HTTPS
application origin. Cleartext development SMTP is restricted to loopback.

Claim and audit an attempt in a committed transaction before any network effect.
Then lock tenant/delivery, recheck authority and send with a bounded timeout while
holding the tenant revocation lock. The delivery's stable Message-ID is independent
of retries/profile rotation. Record sanitized final outcome and immutable attempt
atomically. Crash or commit loss after sending leaves a durable claim: after its
lease expires, record uncertain outcome and stop. No automatic resend of uncertain
claims. Concurrent workers honor the claim lease and cannot both send. Acknowledged
SMTP DATA acceptance means provider acceptance, never proof of mailbox delivery.

Explicit pre-DATA failures and negative SMTP replies permit bounded safe retry;
connection loss during DATA is uncertain. Automatic retry stops at eight attempts;
reviewed replay can continue to the lifetime twenty-attempt cap, preserving all
history. Replay requires current administrator authority, exact state SHA-256 and
a reason. Accepted/skipped deliveries are terminal. Redis acknowledgements never
define delivery completion. Scoped dispatcher batches are capped at 100.

## Rollback and verification

Ledger/source bindings are immutable; attempt evidence cannot be edited/deleted/
truncated. Populated downgrade refuses before dropping evidence; use a forward fix
or verified full backup restore with a write replay plan. Test source eligibility,
tenant isolation, revocation, idempotency, duplicate workers, lease recovery, safe
retry, uncertainty, replay conflicts/caps, SMTP protocol and secret redaction.
SMTP tests use only fake transports or loopback sinks; no external mail is sent.
Phase 6 remains open and Core remains industry-neutral.

## Explicit source capture extension

ADR-0021 implements the previously pending per-invitation/per-rule capture handoff.
Immutable notify channels can now explicitly request email; manual defaults and
automatic task/workflow in-app projections are preserved. Delivery/replay semantics,
tenant secrets and fresh original queue authority remain as decided above.
