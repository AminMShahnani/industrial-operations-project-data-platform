# Project Status

Status: PHASE 2 PREPARATION ? SECURITY DECISION PENDING
Current phase: Phase 2 ? projects, departments and master data (preparation)
Last updated: 2026-10-05
Overall completion: 2/11 phases accepted. Phase 0: 8/8 criteria satisfied.
Phase 1: P1-01?08 pass (8/8), hosted run 37325939172 on commit 3135ff8. Later phase detailed
criteria are not yet written; no unsupported project-wide percentage is reported.

## Completed modules
- Foundation tooling, observability, module boundaries, infrastructure and CI.
- Phase 1 identity, organizations/settings, workspaces, scoped IAM and audit slices.
- Typed API/client and OIDC administration shell; provider/operator runbook.

## In progress
- Phase 2 acceptance checklist written (0/8 accepted); ADR-0007 proposed.
- No Phase 2 feature code, permissions or migrations have been applied.

## Blocked
Q-003: global master-data publication authority is unspecified in docs/14.
Recommended audited operator-only publishing; tenant access read-only.
AGENTS.md requires stopping rather than guessing security-sensitive ownership.
Production provider configuration remains deployment-owned. No legacy export supplied.

## Next 5 tasks
1. Resolve Q-003 global master-data publication authority and accept ADR-0007.
2. Record project lifecycle/access and master-data schema decisions in ADRs.
3. Add typed project/department/master-data contracts and tenant-safe migrations.
4. Implement audited services and positive/negative authorization tests.
5. Add administration slices and run every Phase 2 quality gate.

## Test status
41 backend tests pass locally, no skips: unit, API isolation/security, PostgreSQL
migration roundtrip/immutability, Redis/private S3, real Keycloak PKCE browser flow.
Frontend: 3 tests pass; lint, strict types and production build pass.
Ruff lint/format, strict mypy (134 files), Alembic drift, OpenAPI drift and
regenerated TypeScript API contract pass. Full fail-fast script passes.
Hosted run 37325939172 passes backend/frontend on final code commit 3135ff8,
including all 41 backend tests, 3 frontend tests, real PKCE login, migrations,
lint/types/build and API contract drift. Phase 1 accepted; Phase 2 not started.

## Migration status
`34c1f0cc7d24` applied in development and isolated test databases. Empty migration
roundtrip and schema drift pass; populated downgrade refuses before data removal.
Audit mutation triggers and composite tenant FKs tested. No legacy migration.
Local corrected Compose images and private RustFS bucket now verified; the earlier
Phase 0 workstation image-download limitation has been resolved.

## Known tech debt
TD-001?004: deployment telemetry/alerts, production web hardening, legacy fixtures
and production identity/runtime DB role provisioning. See TECH_DEBT.md.
