# AGENTS.md — Codex Execution Contract

## Mission
Build the production-grade Industrial Operations Platform described in `docs/`. The current MVP is reference material only; do not preserve weak architectural choices for compatibility unless a migration requirement explicitly says so.

## Source of truth
Read these files before implementation:
1. `docs/00_README.md`
2. `docs/01_PRODUCT_VISION.md`
3. `docs/02_SCOPE_AND_RELEASES.md`
4. `docs/03_FUNCTIONAL_REQUIREMENTS.md`
5. `docs/04_NON_FUNCTIONAL_REQUIREMENTS.md`
6. `docs/05_DOMAIN_MODEL.md`
7. `docs/06_MULTI_TENANCY.md`
8. `docs/07_IAM_AND_AUTHORIZATION.md`
9. `docs/08_WORKSPACE_PROJECT_MODEL.md`
10. `docs/09_FORM_ENGINE.md`
11. `docs/10_WORKFLOW_ENGINE.md`
12. `docs/11_SCHEDULING_AND_TASKS.md`
13. `docs/12_AUTOMATION_ENGINE.md`
14. `docs/13_DOMAIN_PACK_ARCHITECTURE.md`
15. `docs/14_MASTER_DATA.md`
16. `docs/15_REPORTING_AND_DASHBOARDS.md`
17. `docs/16_INTEGRATIONS.md`
18. `docs/17_TECHNICAL_ARCHITECTURE.md`
19. `docs/18_DATA_ARCHITECTURE.md`
20. `docs/19_API_AND_EVENTS.md`
21. `docs/20_SECURITY.md`
22. `docs/21_FRONTEND_UX.md`
23. `docs/22_TESTING_STRATEGY.md`
24. `docs/23_OBSERVABILITY_AND_OPERATIONS.md`
25. `docs/24_MIGRATION_FROM_MVP.md`
26. `docs/25_ROADMAP.md`
27. `docs/26_CODING_STANDARDS.md`
28. `docs/27_CODEX_EXECUTION_PLAN.md`
29. `docs/28_DEFINITION_OF_DONE.md`

## Hard rules
- Implement by phase. Do not skip phases.
- Do not silently change domain rules. If a contradiction is found, create an ADR under `docs/adr/` and record the decision.
- Core must remain industry-neutral. Industry-specific behavior belongs in Domain Packs.
- No customer-specific fork of Core.
- All authorization must be enforced server-side.
- Every write that matters operationally must produce an immutable audit event.
- Form definitions and workflow definitions are versioned and immutable after activation.
- Never execute arbitrary user-authored Python/JS for formulas or automations.
- All background work must be idempotent.
- Every migration must be reversible or have a documented rollback strategy.
- Prefer explicit schemas and typed contracts over unstructured dictionaries.
- Every feature requires tests before phase completion.

## Progress protocol
Maintain these files during implementation:
- `docs/progress/PROJECT_STATUS.md`
- `docs/progress/PHASE_LOG.md`
- `docs/progress/OPEN_QUESTIONS.md`
- `docs/progress/TECH_DEBT.md`

At the end of each phase:
1. run unit/integration tests;
2. run lint/type checks;
3. update progress files;
4. list completed acceptance criteria;
5. list deferred items;
6. commit with a phase-oriented message.

## Implementation style
Use modular-monolith boundaries first. Modules own their domain logic and persistence access. Cross-module communication should use application services and domain/integration events, not direct table access from unrelated modules.

## Stop conditions
Stop and document instead of guessing when:
- a security-sensitive requirement is ambiguous;
- a migration could lose data;
- a domain rule conflicts with another source-of-truth document;
- a design would couple Core to a specific industry/customer.
