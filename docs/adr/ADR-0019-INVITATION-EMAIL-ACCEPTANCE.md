# ADR-0019: Invitation email acceptance

Date: 2026-10-10
Status: Accepted; user delegated the choice with "do best" on 2026-10-10

## Context

Phase 6 requires durable email and invitation adapters. ADR-0006 requires random
one-time invitation tokens with only SHA-256 digests stored. ADR-0011 prohibits
tokens in Redis and plaintext outbox payloads. A worker cannot reconstruct a token
from its digest. Acceptance currently also requires matching OIDC-verified email,
seven-day expiry, unused state and fresh inviter delegation.

Persisting recoverable tokens or removing possession from acceptance changes a
security boundary. AGENTS.md requires resolving this ambiguity before coding.

## Options

1. Recommended: email a token-free sign-in link. Introduce a distinct email
   invitation mode requiring authenticated matching OIDC-verified normalized email,
   unused state, expiry, active organization and fresh inviter authority, checked
   transactionally. Preserve existing bearer-token invitations and their acceptance
   requirements. Invitation IDs alone confer no authority; pending invitations
   are never exposed to unauthenticated callers. Explicitly amend ADR-0006 for
   the new mode rather than weakening existing invitations.
2. Preserve bearer-token acceptance and authorize temporary encrypted token
   storage. Before implementation define tenant isolation, key ownership/rotation,
   decryption authority, expiry and ciphertext disposal. No token may enter broker
   messages, audits, logs or plaintext outbox payloads.

Both preserve seven-day expiry, trusted OIDC verification, fresh inviter authority,
immutable audit and ADR-0011's minimal disclosure, stable Message-ID and controlled
replay following uncertain SMTP acknowledgement. Provider acceptance does not prove
mailbox delivery. No external email is sent during decision review.

## Decision and verification

Select option 1. This explicitly amends ADR-0006 only for new `verified_email`
invitations: no bearer secret is generated or stored. Existing rows default to
`token` and retain their exact digest and possession requirement. Creation and
acceptance are separate audited commands. The link is a public pair of organization
and invitation IDs, with no role, email or credential in its URL. Acceptance never
uses GET, and requires trusted OIDC authentication plus the verified matching email.
No pending-invitation listing or unauthenticated invitation preview is introduced.
Workspace-scoped invitations require a currently active target workspace at creation
and acceptance; organization-scoped invitations bind exactly to their organization.

Creation accepts a caller-generated UUIDv7 request ID scoped to the organization;
retries return the same invitation only when immutable email, role, scope, mode and
inviter match, with fresh delegation checks. Other reuse conflicts. Acceptance
serializes tenant-first and invitation-second with the existing revocation locks;
an already used invitation remains invalid, without duplicate grants or audits.
The PostgreSQL mode/digest check prohibits mixed credentials; invitation binding
fields are immutable and acceptance is one-way. Populated downgrade refuses if any
verified-email invitation exists. Use a forward fix or verified backup restore;
never invent bearer digests or delete invitation history to downgrade.

The first vertical slice implements lifecycle/API/browser acceptance and manually
shared links. It does not claim to send email. Durable SMTP dispatch, attempt
evidence, uncertain outcomes and controlled replay remain required Phase 6 work,
under ADR-0011. No third-party credential storage is added by this slice.
Verify isolation, verified-email binding, live revocation, expiry, concurrent
acceptance, retry identity, immutable binding and rollback. Phase 6 remains open;
Phase 7 is unstarted.
