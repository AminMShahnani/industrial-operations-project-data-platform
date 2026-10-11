# Phase 10 hardening and release evidence

Phase 10 separates reproducible repository checks from deployment evidence. Local
tests do not certify production ingress, backup providers, production scale or UAT.
Record the candidate commit, environment, operator and evidence for each deployment
drill; redact credentials and customer data.

## API security checks

The API emits `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin` and a restrictive
`Permissions-Policy`. The API test suite checks these headers on responses. CORS
origins are explicit and the application does not trust forwarded client-address
headers. Rate limiting fails closed when Redis is unavailable. Production ingress
must preserve the real client boundary without accepting spoofed forwarding headers.

The API does not serve the frontend. The static host/CDN must set a tested CSP,
HTTPS redirect and HSTS policy, and prevent public access to `/metrics` and other
operations endpoints. Validate headers against the built frontend and all required
OIDC/API connections before rollout; do not infer production coverage from Vite's
development server. Production identity provider, restricted runtime/migration DB
roles and ingress policy are separate deployment evidence.

## Local reproducible quality gate

Use isolated databases whose names end in `_test` and `_browser_test`; never point
this gate at a development or production database. Start PostgreSQL, Redis, private
object storage and the local OIDC fixture, then create fresh test databases:

```powershell
docker compose --profile oidc-dev up -d --wait
docker compose exec -T postgres createdb -U operations operations_test
docker compose exec -T postgres createdb -U operations operations_browser_test
$env:IOP_TEST_DATABASE_URL = 'postgresql+psycopg://operations:operations_dev@127.0.0.1:55432/operations_test'
$env:IOP_BROWSER_DATABASE_URL = 'postgresql+psycopg://operations:operations_dev@127.0.0.1:55432/operations_browser_test'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

The gate runs static checks, non-browser tests, migration upgrade/drift against the
isolated test DB, real OIDC/PKCE browser tests against the separate browser DB, and
frontend lint/type/test/build checks. Browser tests retain their own test history;
use a fresh database for a reproducible run. CI remains the exact-hosted gate.

## Backup and restore drill

No production backup provider, encryption-key boundary, object-store snapshot
mechanism or restore environment is configured in this repository. Before accepting
P10-03, the deployment owner must configure daily encrypted backups with RPO no
greater than 24 hours and execute a restore drill. PostgreSQL and private object
storage are both operational data stores; a database-only dump is not a complete
platform backup.

For the drill, stop new writes and drain workers/dispatchers, capture a PostgreSQL
backup and a private object-store backup under the same maintenance window, record
the database revision and object inventory/checksums, and protect backup material
with the deployment key manager. Restore both stores into isolation with the exact
candidate configuration. Verify PostgreSQL integrity and `alembic check`, audit
history, object counts/checksums, representative attachment/export reads, API
readiness and worker recovery before recording elapsed restore time and achieved
recovery point. Do not switch production traffic or remove the source backup as part
of the drill. The deployment must separately define its measured restore objective.

## Migration and legacy rehearsal

Every schema revision must upgrade on a clean database and pass Alembic drift checks.
For populated history, use the migration's guarded rollback behavior; prefer a
reviewed forward repair. If a documented rollback requires restoration, restore the
database and matching object snapshot to isolation, reconcile writes, and record the
cutover plan. Never clear retained operational or audit data to force a downgrade.

The legacy Mongo source export and immutable fixtures have not been supplied. Do not
run a cutover or claim count/checksum/parallel-read validation until the collection
inventory and authorized export are available. Then preserve source IDs in migration
metadata, map all five documented record families and organization/workspace/project
scopes, compare counts and checksums, and run parallel reads before cutover.

## Performance and UAT evidence

The release candidate must be measured under a documented workload representing
the scale assumptions in docs/04. Record p50/p95/p99, errors, database pool and queue
behavior for typical authenticated API calls, form metadata and first-page task inbox.
Verify the targets in docs/04 without loading all submissions into memory. No
production-scale load environment is configured here, so unit-test timings are not
acceptance evidence.

UAT must be performed by the product owner and representative operational users on
the deployed candidate. Record tested workflows, defects, accessibility findings
and sign-off. Local Playwright tests cover the configured browser flows but do not
substitute for production identity, ingress or owner acceptance.
