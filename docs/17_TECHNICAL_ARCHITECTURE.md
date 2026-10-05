# Technical Architecture

## Recommended V1 architecture
Modular monolith + background worker(s), designed for later service extraction only where scaling/ownership requires it.

## Suggested stack
Backend: Python 3.13+, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic.
Database: PostgreSQL.
Cache/locking/queue support: Redis.
Background jobs: Celery/Dramatiq/Arq selection via ADR; choose one and standardize.
Object storage: S3-compatible API.
Frontend: TypeScript + React/Next.js (final choice via ADR).
Observability: OpenTelemetry + structured logs + metrics/error tracking.

## Layering
API -> Application -> Domain -> Infrastructure.
Domain modules must not depend on FastAPI/ORM details.

## Modules
identity, organizations, workspaces, projects, iam, forms, submissions, workflows, scheduling, tasks, automation, master_data, files, notifications, reporting, domain_packs, integrations, audit.

## Events
Domain events are in-process durable intent; integration events use outbox pattern for background publication.

## Why not microservices first
Complex distributed consistency would slow delivery. Strong module boundaries preserve an extraction path.
