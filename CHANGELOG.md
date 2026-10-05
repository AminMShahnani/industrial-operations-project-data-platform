# Changelog

## 0.2.0 — Phase 1 identity and scoped administration (2026-10-05)
- Add configurable OIDC access-token verification and browser Authorization Code + PKCE.
- Add tenant identities, organizations/settings, workspaces and scoped server-side RBAC.
- Add constrained grants, verified-email invitations and lifecycle revocation/reactivation.
- Add transactional immutable audit, composite tenant foreign keys and safe rollback guards.
- Add typed API/client contracts, administration shell and operator/auth runbook.
- Add security/isolation API tests and real Keycloak browser acceptance to CI.

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
