# ADR-0004: Foundation runtime and tooling

Status: Accepted
Date: 2026-10-05

## Decision
Use Python 3.14 (within the documented 3.13+ target), FastAPI/Pydantic,
synchronous SQLAlchemy 2 and psycopg 3, Alembic, uv with a committed lockfile,
Ruff and strict mypy. HTTP endpoints that access blocking infrastructure run as
sync endpoints in FastAPI's thread pool. Domain objects remain framework-free.

Use React with Vite and strict TypeScript for a SPA. Server rendering is not
required for authenticated operations. All access decisions remain server-side.
Use npm's lockfile for reproducible frontend installs. This resolves the frontend
framework question without altering product scope.

Use PostgreSQL 16, Redis 7 and an S3-compatible development service in Compose.
Development credentials and bindings are local-only; production uses externally
managed secrets, TLS and private networking. Do not automatically migrate on API
startup. Phase 0 has an empty reversible baseline, not speculative business tables.

## Consequences
Python 3.14 is needed locally and in CI. The SPA needs a production static-hosting
and CSP configuration in hardening. Workers, identity and sortable IDs require
their own ADRs before implementation; no queue framework is selected prematurely.

## Foundation revision (2026-10-05)
Initial scaffolding selected PostgreSQL 17 and a tagged MinIO image. Registry pulls
stalled locally. Before any schema/data is created, standardize on the available
PostgreSQL 16 and MinIO images pinned by registry digest, for identical local/CI
infrastructure. This changes no product rule or existing data. Database upgrades
require separate compatibility and migration validation; no silent version change.

## Observability
Use an app-owned OpenTelemetry tracer provider with optional OTLP/HTTP export
and Prometheus counters/latency histograms. Labels contain bounded status classes
only; arbitrary URLs and request data are excluded. Close providers on shutdown.
Deployment keeps metrics private; the development server binds locally.

## References
- docs/17_TECHNICAL_ARCHITECTURE.md
- docs/18_DATA_ARCHITECTURE.md
- https://fastapi.tiangolo.com/advanced/events/
- https://alembic.sqlalchemy.org/en/latest/tutorial.html
