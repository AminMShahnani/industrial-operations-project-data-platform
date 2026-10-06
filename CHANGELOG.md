# Changelog

## 0.5.0 - Phase 4 scheduling and shared tasks (2026-10-06)
- Add immutable schedule versions, bounded timezone-aware recurrence and scoped shifts/triggers/milestones.
- Add idempotent shared occurrences, atomic claims, private drafts and transactional task submission.
- Add scoped My Work, version administration and durable in-app reminders with periodic CLI.
- Add tenant-safe migrations/history protection, ADR-0009 and the Phase 4 runbook.
- Accept all 8 Phase 4 criteria: 111 backend tests, 9 frontend tests; hosted run
  37432881526 passes backend/frontend on code commit d92a10f.

## 0.4.0 - Phase 3 governed forms (2026-10-05)
- Add immutable versioned forms, reusable pinned libraries and bounded declarative expressions.
- Add scoped Form Studio, authoritative runtime validation, autosave and immutable submissions.
- Add private attachments, fail-closed scanning, signed downloads and rollback compensation.
- Add guarded migrations, ADR-0008 and operational guidance.
- Accept all 8 Phase 3 criteria: 90 backend tests, 7 frontend tests; hosted run
  37363436134 passes backend/frontend on code commit fad771b.

## 0.3.0 - Phase 2 projects and governed master data (2026-10-05)
- Add audited projects, controlled immutable lifecycle definitions and scoped roles.
- Add departments/teams, independent memberships and department-project grants.
- Add typed scoped master data, validated atomic CSV/XLSX imports and paged exports.
- Add audited operator-only global publication and read-only tenant reference access.
- Add immutable relational history, guarded rollback and typed administration UI.
- Add isolation, permission, migration and real browser acceptance coverage.
- Accept all 8 Phase 2 criteria: 63 backend tests, 5 frontend tests; hosted run
  37350474988 passes backend/frontend on code commit 5c0d19b.

## 0.2.0 — Phase 1 identity and scoped administration (2026-10-05)
- Add configurable OIDC access-token verification and browser Authorization Code + PKCE.
- Add tenant identities, organizations/settings, workspaces and scoped server-side RBAC.
- Add constrained grants, verified-email invitations and lifecycle revocation/reactivation.
- Add transactional immutable audit, composite tenant foreign keys and safe rollback guards.
- Add typed API/client contracts, administration shell and operator/auth runbook.
- Add security/isolation API tests and real Keycloak browser acceptance to CI.
- Accept all Phase 1 gates: 41 backend tests, 3 frontend tests; hosted run 37325939172 passes.

## 0.1.0 — Phase 0 foundation (2026-10-05)
- Establish locked Python/FastAPI/SQLAlchemy/Alembic tooling and strict checks.
- Add typed health endpoints, sanitized problem details, structured logs, HTTP metrics and tracing.
- Define module/layer boundaries with automated enforcement.
- Add reversible empty PostgreSQL baseline and real-infrastructure integration tests.
- Add local PostgreSQL/Redis/private object storage and React/TypeScript shell.
- Add quality CI, versioned OpenAPI, stack ADR, phase backlog and runbook.
- Correct registry image pins and replace unavailable development MinIO with
  S3-compatible RustFS on a separate volume; preserve the original volume (ADR-0005).
- Complete all Phase 0 acceptance criteria with successful hosted CI run 37316897694.
