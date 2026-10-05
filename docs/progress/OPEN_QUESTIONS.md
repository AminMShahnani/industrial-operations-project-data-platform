# Open Questions

## Phase 0 blockers
None. Remote configuration and required hosted CI are resolved.

## Security decisions required before Phase 1
- Q-002: Select the initial trusted identity provider or explicitly require
  first-party credentials. Define organization identity linkage, platform-admin
  bootstrap, invitation verification and token/session trust requirements.
  docs/20 permits alternatives but does not select a deployment trust model.
  Do not introduce a temporary authentication bypass to avoid this decision.
  User asked on 2026-10-05 to select configurable OIDC or first-party credentials;
  answer pending. Phase 1 implementation has not started.

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
