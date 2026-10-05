# Coding Standards

## General
Readable explicit code over clever abstractions. Keep domain logic out of routers/controllers.

## Python
- ruff formatting/linting
- mypy/pyright strict-enough configuration
- Pydantic schemas at boundaries
- SQLAlchemy typed models/repositories
- no mutable default args
- UTC-aware datetimes
- `Decimal` for controlled numeric precision where needed

## Module rules
A module exposes application interfaces. Other modules must not import its infrastructure repositories directly.

## Database
All schema changes via Alembic. Foreign keys and unique constraints enforce invariants where practical.

## APIs
Stable error codes, consistent pagination/filtering, no leaking ORM entities directly.

## Frontend
Strict TypeScript, generated API client/types where practical, centralized permission-aware components, accessible forms.

## Documentation
Public module boundaries and non-obvious domain rules require concise docs. Significant trade-offs require ADRs.
