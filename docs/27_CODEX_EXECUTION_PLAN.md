# Codex Execution Plan

## Startup procedure
1. Read `AGENTS.md` and all numbered docs.
2. Inspect repository state and current code.
3. Create/update `docs/progress/PROJECT_STATUS.md`.
4. Create an implementation backlog grouped by roadmap phase.
5. Do not start feature code until Phase 0 acceptance criteria are written.

## For every phase
A. restate relevant requirements in the phase log.
B. design/update ADRs if needed.
C. add migrations/contracts first.
D. implement smallest complete vertical slices.
E. add unit + integration/API tests.
F. run all quality checks.
G. update docs/progress and changelog.
H. mark acceptance criteria pass/fail with evidence.

## Progress format
`PROJECT_STATUS.md` must contain:
- current phase
- overall completion estimate by completed acceptance criteria, not intuition
- completed modules
- in-progress items
- blocked items
- next 5 tasks
- test status
- migration status
- known tech debt

## Prohibited Codex behavior
- rewriting scope without documenting decision;
- introducing a new framework without ADR;
- skipping tests to advance phases;
- embedding Oil & Gas fields inside Core tables;
- using untyped dict blobs where a domain contract exists;
- adding temporary auth bypasses outside development-only fixtures.
