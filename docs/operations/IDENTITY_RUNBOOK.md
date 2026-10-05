# Phase 1 identity and hierarchy runbook

## Trust and local login

The API accepts bearer access tokens only. Configure `IOP_OIDC_ISSUER`,
`IOP_OIDC_JWKS_URL`, `IOP_OIDC_AUDIENCE` together. Production trust endpoints
require HTTPS. Default `IOP_OIDC_PROFILE=rfc9068` requires RS256 `at+jwt` access
tokens; `keycloak` requires RS256 `JWT` with signed payload `typ=Bearer`.
Expiration, issue time, subject and audience are mandatory. Maximum lifetime is
`IOP_OIDC_MAX_TOKEN_LIFETIME` (default 3600 seconds, cannot exceed 3600).
Provider roles and tenant claims do not confer application permissions.

For an isolated development provider:

```powershell
docker compose --profile oidc-dev up -d --wait
```

Uncomment the four OIDC entries in root `.env.example` when copying them into
`.env`. Copy `frontend/.env.example` to `frontend/.env.local`, set
`VITE_OIDC_AUTHORITY=http://127.0.0.1:58080/realms/operations` and
`VITE_OIDC_CLIENT_ID=operations-web`. Start the API and frontend as in README.
The fixture account is `dev-platform`, password `development-only-change-me`;
override `IOP_OIDC_DEV_PASSWORD` before importing the realm if desired. These
are public development credentials, never a production setup. The provider has
no persistent volume; recreating its container resets fixture users/sessions.
Keycloak's `basic` client scope supplies the required subject claim.

## Operator bootstrap and organizations

Provision a known subject from the configured trusted issuer:

```powershell
uv run python scripts/bootstrap_admin.py --subject dev-platform --reason "Local operator setup"
```

There is no HTTP bootstrap endpoint. Authenticate normally, then POST
`/api/v1/organizations` with `name`, `admin_subject`, `admin_email`, and optional
typed `settings`. The operator explicitly selects the initial organization admin.
Platform administrators can create, suspend and resume organizations; they do
not automatically gain operational tenant access. The organization admin uses
the browser workspace and invitation forms, or the typed API at `/docs`.

Invitation codes are shown once to an authorized grant writer. Share through
your approved channel; automated delivery belongs to Phase 6. Acceptance requires
a matching verified email, live inviter authority and an unused code within seven
days. Revocation preserves identity and audit history. Reinviting reactivates the
same organization identity. Users cannot change their own grants or delegate
permissions they lack at the target scope.

Browser tokens stay in memory; PKCE handshake state uses session storage.
Reloading requires another provider authorization; “Sign out here” clears the
local application session. Provider session termination is managed by the provider.
API rate limits default to 600 requests/minute per directly connected address;
configure `IOP_API_RATE_LIMIT` for the ingress topology. Forwarded headers are
not trusted. Redis failure denies protected requests rather than bypassing limits.

## Migrations and rollback

Apply `uv run alembic upgrade head`; verify `uv run alembic check`.
Revision `34c1f0cc7d24` creates tenant-scoped hierarchy, grants, invitation and
audit tables. Composite foreign keys prevent cross-tenant user/workspace grants.
UPDATE, DELETE and TRUNCATE of audit events are rejected by database triggers.
Use a restricted production runtime database role: it must not own tables, be
superuser, alter schema, disable triggers or run migrations. Provision the
migration/backup operator separately. Operators with database administration
privileges are trusted and remain subject to deployment audit controls.

The downgrade succeeds only if every Phase 1 table is empty; populated downgrade
refuses before any schema removal. Before production upgrade, take and verify a
PostgreSQL backup and matching application configuration. On a populated failure,
prefer a reviewed forward fix; otherwise restore the verified backup into a
separate database and validate counts/audit history before switching the service.
Never clear business or audit tables to force a downgrade. No legacy migration
was attempted: source data has not been provided.

## Acceptance checks

Create `operations_test` and `operations_browser_test` once, set their respective
`IOP_TEST_DATABASE_URL` and `IOP_BROWSER_DATABASE_URL`, and start `oidc-dev`.
The first database must contain no operational data; API fixtures roll back their
transactions. Browser fixtures use a separate database and retain only test history.
Install Chromium with `uv run playwright install chromium` (Linux CI also uses
`--with-deps`). Run `scripts/check.ps1`; skips do not satisfy phase acceptance.
CI exercises real PostgreSQL, Redis, private S3 storage and Keycloak PKCE login.

References: [Keycloak client scope change](https://github.com/keycloak/keycloak/blob/main/docs/documentation/upgrading/topics/changes/changes-25_0_0.adoc),
[realm import](https://www.keycloak.org/server/importExport), ADR-0006.
