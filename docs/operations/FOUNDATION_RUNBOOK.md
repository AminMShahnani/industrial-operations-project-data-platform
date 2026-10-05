# Foundation operations

## Startup and diagnostics
Use the README setup. Containers bind to loopback and use project-named volumes.
The development initializer creates a private bucket without an anonymous policy.
It refuses non-development environments. PostgreSQL is the source of truth;
Redis and object storage do not replace operational relational persistence.

`docker compose ps` shows container health. `docker compose logs --tail 100`
shows dependency startup. API request logs are JSON with UTC timestamp, request
and correlation UUIDs, status and duration. Unauthenticated foundation health
requests have null organization/actor; future authenticated context supplies these.
Request bodies, queries and arbitrary exception messages are excluded from logs.
Supplied correlation/request identifiers must parse as UUIDs; otherwise they are
replaced. Liveness is independent of external services; readiness requires all three.

`/metrics` exposes HTTP counts by status class and latency histogram. In production,
restrict this operations endpoint at the ingress. Spans accept W3C trace context,
record generated request/correlation IDs and status, and omit exception details.
Set `IOP_OTLP_ENDPOINT` to an OTLP/HTTP collector's `/v1/traces` endpoint to export
spans. Without it, no exporter is configured. Trace IDs accompany request logs.

## Baseline migration rollback
The baseline `0001_foundation` creates no business tables. It establishes the
Alembic revision marker. For an isolated foundation database:

1. Stop API processes before migration work.
2. Confirm the database URL names the intended database; take a database backup
   before applying future data/schema migrations.
3. Run `uv run alembic current` and record the revision.
4. Run `uv run alembic downgrade base` (foundation only).
5. Run `uv run alembic upgrade head`, then `uv run alembic check`.
6. Start the API; confirm readiness.

No operational data exists at this revision. Each future migration must document
its own data-safe rollback; this procedure must not be assumed safe for later
business revisions. Tests exercise upgrade/downgrade/upgrade on a separate database.
Never run tests against a production database.

## Reproducibility and CI
`uv.lock`, `frontend/package-lock.json` and image digests capture dependencies.
CI uses frozen/clean installs, separate database tests and OpenAPI drift checks.
The local workspace has no configured Git remote at startup. Local gate evidence
is recorded separately from hosted CI; a green hosted run is required for phase
completion under docs/28. Do not equate a workflow file with a successful CI run.

## Later operational requirements
Production secret management, TLS, private metrics exposure, collector deployment,
monitoring alerts, backup/restore drills, key rotation and failed-job
replay procedures are delivered with their owning features and Phase 10.
This runbook does not certify production readiness or restore objectives.
