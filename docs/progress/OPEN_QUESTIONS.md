# Open Questions

## Blocking phase completion
- Q-001 (Phase 0): Which Git remote/CI host should receive this repository?
  There was no Git repository or remote initially. Local gates pass, but
  docs/28 requires the complete checklist to pass in CI. A workflow file is
  present; no hosted run is available. Remote information requested on 2026-10-05.

## Security decisions required before Phase 1
- Q-002: Select the initial trusted identity provider or explicitly require
  first-party credentials. Define organization identity linkage, platform-admin
  bootstrap, invitation verification and token/session trust requirements.
  docs/20 permits alternatives but does not select a deployment trust model.
  Do not introduce a temporary authentication bypass to avoid this decision.

## Questions that do not block Phase 0
- job queue library choice;
- exact enterprise deployment topology (cloud/on-prem/hybrid);
- retention requirements by customer/industry;
- legal requirements for electronic signatures in target markets.

## Resolved
- Frontend: React SPA with Vite, strict TypeScript (ADR-0004).
- Repository inventory: docs only; legacy code and production data not supplied.

Codex must not guess business-critical answers. Record assumptions and use configurable abstractions when possible.
