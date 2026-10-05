# Open Questions

## Phase 0 blockers
None. Remote configuration and required hosted CI are resolved.

## Resolved Phase 1 security decision
- Q-002: Select the initial trusted identity provider or explicitly require
  first-party credentials. Define organization identity linkage, platform-admin
  bootstrap, invitation verification and token/session trust requirements.
  docs/20 permits alternatives but does not select a deployment trust model.
  Do not introduce a temporary authentication bypass to avoid this decision.
  User asked on 2026-10-05 to select configurable OIDC or first-party credentials;
  User delegated the choice: OIDC selected in ADR-0006; question resolved.

## Questions that do not block Phase 0
- job queue library choice;
- exact enterprise deployment topology (cloud/on-prem/hybrid);
- retention requirements by customer/industry;
- legal requirements for electronic signatures in target markets.

## Resolved
- Repository remote: https://github.com/AminMShahnani/industrial-operations-project-data-platform
- Q-001: `main` tracks `origin/main`; hosted run 37316897694 passes both jobs.
- Frontend: React SPA with Vite, strict TypeScript (ADR-0004).
- Repository inventory: docs only; legacy code and production data not supplied.

Codex must not guess business-critical answers. Record assumptions and use configurable abstractions when possible.

Phase 1 final hosted run 37325939172 passes. No unresolved Phase 1 question.

## Resolved Phase 2 security decision
- Q-003: User selected audited operator publication on 2026-10-05.
  Global reference data is read-only to tenants; platform administration never
  grants tenant operational access. ADR-0007 is accepted. No unresolved Phase 2 blocker.

## Phase 3 decisions
No unresolved security-sensitive Phase 3 question. ADR-0008 records scoped privacy,
restricted fields, declarative evaluation, immutable snapshots and fail-closed files.
Basic authenticated acknowledgement is V1; configurable signatures stay V1.5.
Shift and previous-approved defaults have trusted ports; authoritative records are
owned by Phase 4/5, with explicit unavailable-context errors until connected.
