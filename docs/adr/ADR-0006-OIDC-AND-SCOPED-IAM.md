# ADR-0006: OIDC authentication and Phase 1 scoped authorization

Status: Accepted
Date: 2026-10-05

## Decision
The user delegated the authentication choice. Choose OIDC with externally managed
credentials. The API is a resource server accepting signed, short-lived RS256
JWT access tokens from one explicitly configured issuer, JWKS URL and API audience.
Require exp/iat/iss/sub/aud and an explicitly configured access-token discriminator
(default RFC 9068 `typ=at+jwt`). Never accept ID tokens or provider role claims as
application grants. No client-supplied tenant claim confers membership.
JWKS discovery is configuration-owned, bounded/cached and never taken from token
headers. Production requires HTTPS endpoints. Without complete trust configuration,
protected APIs fail closed. Authentication failures produce sanitized audit events.

Browser clients use Authorization Code + PKCE through the configured provider;
API credentials are bearer tokens, never query parameters or application cookies.
Authentication is separate from persisted application authorization. The server
does not manage passwords, refresh tokens or provider accounts. Tenant users are
organization identities linked to the verified `(issuer, subject)` pair. Removing
access changes lifecycle state, never deletes historical users or grants.

Use UUIDv7 from Python 3.14 for new persisted identities and UTC timestamps.
Organization/workspace grants have explicit inheritance and validity windows.
OrganizationAdmin explicitly inherits organization permissions to workspaces;
workspace roles apply only to their workspace. Unknown permissions/scopes deny.
Delegated grant writers cannot grant permissions they lack at the target scope,
change their own grants, or grant across organizations. Membership alone is not
a permission grant. Suspend organizations/users without erasing history.

Platform administrators are provisioned only by an explicit operator CLI using a
trusted issuer and known subject, with an immutable audit event. Their platform
role allows organization creation/suspension; it does not bypass tenant policies
or grant access to operational content. Organization creation names the initial
admin subject explicitly and audits its membership and organization grant.
Platform support impersonation is not part of Phase 1.

Invitations use random one-time tokens, store only SHA-256 digests, expire after
seven days, and bind to the invitee's verified normalized email. Acceptance creates
or reactivates the organization identity and explicit grants transactionally.
Administrators preview the invitation target/role in the create command; invitation
delivery is a Phase 6 adapter. Tokens are returned once to the authorized caller
and never logged. Authorization is rechecked on acceptance so a revoked inviter
cannot leave a privileged invitation usable.

Phase 6 amendment: accepted ADR-0019 adds a distinct `verified_email` invitation
mode after the user delegated its policy choice on 2026-10-10. New-mode invitations
generate/store no bearer secret and require a trusted matching OIDC-verified email
plus fresh inviter authority for one-time acceptance. Existing `token` invitations
retain the random token, digest-only storage, expiry and possession requirement
above; they cannot be accepted through the new mode. Delivery remains a Phase 6
adapter. See ADR-0019 for migration, immutable binding and rollback requirements.

Business writes and immutable audit appends share one PostgreSQL transaction.
Audit UPDATE/DELETE/TRUNCATE are prohibited by database triggers. Schema rollback
is permitted only on empty Phase 1 tables; a populated database requires backup
restore or a forward fix, avoiding loss of operational/security history.

## Consequences
Keycloak is an optional loopback-only development/CI fixture, using a registry-pinned
26.8.0 image and a development realm with PKCE enforcement, API audience mapping
and password grant disabled. It does not choose a customer production provider.
Its sample account/password exists only in the opt-in `oidc-dev` Compose profile.
JWT lifetime is bounded to at most one hour (development tokens: five minutes).
API request limits default to 600/minute per directly connected client address and
are configurable for ingress/NAT topology; untrusted forwarding headers are ignored.

No production identity-provider deployment is guessed: its issuer/audience/JWKS
are configuration. Tokens must meet the documented profile; providers with another
access-token marker require explicit configuration. First-party authentication
and enterprise SAML/SCIM remain out of this phase.

## Sources
- docs/05–08 and docs/20_SECURITY.md
- https://www.rfc-editor.org/rfc/rfc9068.html
- https://pyjwt.readthedocs.io/en/latest/api.html
- https://www.keycloak.org/server/importExport
- https://github.com/keycloak/keycloak/blob/main/docs/documentation/upgrading/topics/changes/changes-25_0_0.adoc
