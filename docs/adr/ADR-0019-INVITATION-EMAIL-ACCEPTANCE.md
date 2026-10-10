# ADR-0019: Invitation email acceptance

Date: 2026-10-10
Status: Proposed; awaiting Q-007

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

Pending Q-007. No schema or runtime behavior changes. Following selection, specify
typed contracts and rollback protection, then test tenant isolation, verified email,
revocation, expiry, concurrent acceptance, duplicate dispatch, uncertain delivery
and audit secrecy. Phase 6 remains open; Phase 7 is unstarted.
