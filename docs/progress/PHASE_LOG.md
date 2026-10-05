# Phase Log

Codex must append a dated section for every implementation phase with acceptance criteria, completed work, test commands/results, migrations and deferred items.

## 2026-10-05 — Phase 0: Repository foundation (started)

Requirements: docs/17–23, 25–28; accepted ADR-0001–0003. Core stays
industry-neutral; domain layers cannot import HTTP/ORM infrastructure.
No business endpoints or authentication bypasses are introduced in this phase.

Acceptance criteria written before feature code:

- P0-01: Locked Python 3.13+ environment; strict lint/types and repeatable tests.
- P0-02: FastAPI `/api/v1` composition root, typed health contracts, sanitized
  problem details, validated request correlation and JSON request logs.
- P0-03: Explicit module ownership and automated layer/boundary checks.
- P0-04: PostgreSQL Alembic baseline upgrades, downgrades and upgrades again;
  no ORM schema creation at runtime; migration drift check passes.
- P0-05: Local PostgreSQL/Redis/private S3-compatible development infrastructure
  documented and health checks distinguish liveness from dependency readiness.
- P0-06: React/TypeScript application shell passes lint, type checks and build;
  communicates its foundation status without pretending business features exist.
- P0-07: CI runs backend tests (including real PostgreSQL), lint, types, migration
  checks, frontend checks and OpenAPI drift validation.
- P0-08: ADRs, startup/rollback instructions, phase backlog and all four progress
  files updated; phase commit created. Phase completion requires CI evidence.

Repository inventory: documentation only; no legacy source or data supplied;
no `.git` directory at startup. Existing MVP review remains reference material.

Initial environment finding: Python 3.14, Node 24, uv and Docker CLI available;
Docker engine unavailable. Real migration validation is a required gate.

### Implementation and evidence
Docker Desktop was started hidden. Dependency pulls initially stalled; ADR-0004
records the pre-schema choice of digest-pinned PostgreSQL 16 and MinIO. All three
project containers subsequently became healthy. No legacy data was touched.

| Criterion | Result | Evidence |
| --- | --- | --- |
| P0-01 | PASS locally | Frozen uv install; Ruff lint/format and strict mypy pass |
| P0-02 | PASS locally | Typed health/errors; UUID correlation; JSON logs; bounded HTTP metrics; OpenTelemetry/W3C context; API negative tests |
| P0-03 | PASS locally | 18 module namespaces; AST checks and forbidden-import regression tests |
| P0-04 | PASS locally | PostgreSQL isolated test: upgrade/downgrade/upgrade, revision checks and Alembic drift check |
| P0-05 | PASS locally | Compose healthy PostgreSQL/Redis/MinIO; private bucket verified; readiness integration test |
| P0-06 | PASS locally | React shell: ESLint 10, strict TypeScript, Vite 8 production build |
| P0-07 | PENDING hosted evidence | Workflow written; equivalent local commands pass; no Git remote configured |
| P0-08 | PASS locally when phase checkpoint is committed | Stack ADR, backlog, runbook, OpenAPI contract, changelog and four progress files |

Final suite: 15 tests pass, including three real-infrastructure integration tests;
no skips or warnings. Commands: `uv run pytest` with `IOP_TEST_DATABASE_URL`,
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`,
`uv run alembic check`, `uv run python scripts/export_openapi.py --check`,
and frontend `npm run lint`, `npm run typecheck`, `npm run build`.
Fail-fast local runner: `scripts/check.ps1`; GitHub workflow: `.github/workflows/quality.yml`.

Migration: `0001_foundation`, empty/reversible baseline; development database at
head. Test database is separate; rollback instructions are in the foundation runbook.

Deferred: hosted CI run (Q-001); authentication/tenant hierarchy/audit features
belong to Phase 1; queue choice to Phase 6; business migrations to owning phases;
production collector/alerts/backup/restore/UAT to Phase 10. Phase 1 has not started.

Phase status: locally verified, awaiting required CI evidence. Checkpoint commit
uses a Phase 0 message and does not claim full phase completion.

### Hosted CI follow-up — 2026-10-05
User provided the GitHub origin; renamed branch to `main` and pushed checkpoint
`70db7b1`. Run 37316167433: frontend PASS, backend FAIL at Docker startup.
Verified local cache digests were not portable registry references. MinIO images
were unavailable from Docker Hub/Quay. ADR-0005 records corrected PostgreSQL/Redis
pins and a separate RustFS development volume, preserving the old volume.
Phase completion remains pending replacement validation and a successful CI run.

### Phase 0 acceptance — 2026-10-05
Commit `1d4f68e` passed hosted run:
https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37316897694

Both backend and frontend jobs passed. Backend clean Compose startup validates
the corrected registry pins; all 15 tests pass, including PostgreSQL migration
roundtrip, Redis, signed object storage roundtrip, denied anonymous downloads,
and real API readiness. Ruff lint/format, strict mypy (including migrations),
Alembic upgrade/drift, OpenAPI drift and frontend lint/types/build all pass.

Final acceptance: P0-01 through P0-08 PASS (8/8). Phase 0 complete. The initial
checkpoint is `70db7b1`, infrastructure correction is `1d4f68e`; this completion
record is committed separately. No business data was migrated or deleted.

Deferred items remain assigned to their owning phases as listed above. Phase 1
has not started: Q-002 authentication choice was requested before security work,
per AGENTS.md's security-ambiguity stop condition.

Workstation note: downloads of corrected images stalled locally; the agent stopped
its pending Compose invocation. Existing development containers/volumes remain
intact on the initial cached images. Clean GitHub CI verified the corrected
RustFS setup. Re-run `docker compose up -d --wait` locally when registry downloads
are available; local validation of the replacement is not claimed here.

## 2026-10-05 — Phase 1: Identity, organizations, workspaces and IAM (started)

User delegated the authentication choice. ADR-0006 selects configurable OIDC,
explicit server-side grants, safe bootstrap/invitations and transactional audit.
Requirements: docs/03 FR-001–011, docs/05–08, 19–20 and 22/28. Departments,
projects and their grants remain Phase 2; no phase is skipped.

Acceptance criteria, written before Phase 1 code:
- P1-01: OIDC signature/issuer/audience/expiry/type validation; missing trust fails
  closed; forged/expired/wrong-tenant/ID tokens tested; failure audit and rate limits.
- P1-02: Audited operator bootstrap; platform create/suspend organizations;
  typed settings; no implicit platform access to tenant content.
- P1-03: Tenant identities, one-time verified-email invitations, membership
  revocation/reactivation preserving authorship; expired/replayed/revoked invites deny.
- P1-04: Organization/workspace scoped role presets and constrained explicit
  grants; deny-by-default and non-escalation matrix; grant writes audited.
- P1-05: Workspace create/read/update and manager grants; tenant-safe persistence,
  archived/suspended resource denial, optimistic concurrency for editable records.
- P1-06: Alembic schema, composite tenant foreign keys, immutable audit triggers;
  empty migration roundtrip/drift; populated downgrade refuses data loss.
- P1-07: Typed protected API and schema contract, administration shell and
  reproducible auth/provider setup instructions, positive and negative tests.
- P1-08: Unit/integration/API tests, lint/types and hosted CI pass; progress,
  changelog, rollback/operations docs and phase-oriented commit updated.

### Phase 1 local acceptance evidence
P1-01?P1-07 PASS locally. P1-08 pending hosted CI; Phase 2 has not started.
Full `scripts/check.ps1` passed: 40 backend tests without skips, 3 frontend tests,
Ruff lint/format, strict mypy (134 files), frontend lint/types/build, Alembic
model drift and OpenAPI drift. Real PostgreSQL/Redis/RustFS tests include empty
migration roundtrip, composite tenant FKs, immutable audit and populated downgrade
refusal. Real Chromium/Keycloak PKCE verifies access tokens via actual JWKS,
workspace creation, audit identity, memory-only tokens and local sign-out.

Provider test caught missing `sub` due omitted Keycloak `basic` scope; corrected
the development realm instead of weakening API validation. Additional negative
checks cover bearer-only transport, rate-limit denial, scope-filtered listing,
archive denial, suspension/recovery, malformed/forged/expired/wrong-audience and
ID tokens, invitation replay/expiry/email mismatch/revoked inviter, self-grant
and delegated escalation, optimistic concurrency and audit failure rollback.

Migration: `34c1f0cc7d24`; rollback documented in IDENTITY_RUNBOOK.md. Operational
history is never cleared to force downgrade. No legacy source/data migration.
Corrected local image downloads completed; all local infrastructure now healthy.
Deferred to owning phases: project/department roles (2), notification delivery
(6), pack/integration enablement (8/6), production deployment hardening (10).
No Core industry semantics introduced. ADR-0006 records delegated auth choice.

Hosted run 37324876007: frontend PASS; backend stopped at Linux mypy because
Windows-only `subprocess.CREATE_NO_WINDOW` was referenced in the browser fixture.
Corrected the platform-conditional constant lookup and added Linux-target mypy
to local gates. This is test process portability; no authentication policy changed.
Phase 1 remains pending until the corrected hosted run passes.

Hosted run 37325375871 on 569550b PASS: backend/frontend, including actual
Chromium PKCE, migrations and contract drift. Final settings validation review
added a negative timezone-path case: ZoneInfo ValueError now maps to 422 rather
than 500. Its API test also covers configured branding/locale/units/timezone,
organization update concurrency and organization admin delegation/audit identity.
All 12 Phase 1 API tests and Linux mypy/lint/format pass. The suite now has 41
backend tests; final corrected-head hosted acceptance remains pending.

### Phase 1 final acceptance
Hosted run: https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37325939172
Code commit: `3135ff8`; initial phase implementation: `879e0cb`.
Final acceptance: P1-01 through P1-08 PASS (8/8). Both jobs succeed, including
40 non-browser backend tests plus real Chromium/Keycloak PKCE, 3 frontend tests,
lint/format/types/build, private infrastructure, migration roundtrip/drift,
OpenAPI and generated TypeScript drift. Full local suite: 41 pass, zero skips.

All four progress files, changelog, ADR and operator/rollback runbook maintained.
Deferred items are explicitly assigned above and in TECH_DEBT.md; no unresolved
Phase 1 blocker. Phase 2 has not started. This evidence is committed separately
with a phase-oriented message after the code-head CI pass.

## 2026-10-05 — Phase 2 preparation

Reviewed AGENTS.md and relevant source requirements: docs/03 FR-012–016,
docs/05–08, 14, 18–20, 21–22, 25–28. Phase 1 hosted gates pass before this work.

Acceptance checklist, written before Phase 2 feature code:
- P2-01: Workspace-owned projects with typed context, dates and controlled lifecycle;
  validated transitions and optimistic concurrency; every operational write audited.
- P2-02: Workspace departments/teams, active membership lifecycle and immutable
  history; membership alone never confers project access.
- P2-03: Independent direct project memberships and department-project grants,
  validity windows, explicit scoped roles, constrained delegation and revocation.
- P2-04: Master-data types with bounded typed schemas/governance; records with
  stable codes/IDs, validity/status and organization/workspace/project/global scope.
- P2-05: CSV/XLSX import validation, duplicate detection, dry-run preview and atomic
  apply; stable code/ID export; no arbitrary expressions or industry Core fields.
- P2-06: Tenant/workspace relational invariants, historical reference protection,
  migration roundtrip/drift and documented populated rollback strategy.
- P2-07: Typed API/generated client and accessible scope-aware administration flows;
  positive, negative, isolation, non-escalation and audit tests.
- P2-08: All local/hosted tests, lint/types/build pass; four progress files,
  ADRs, runbooks/changelog and phase-oriented commits updated.

ADR-0007 records a proposed global reference publishing boundary. docs/14 permits
global data but does not assign write authority. This security decision is Q-003;
AGENTS.md requires documenting and stopping instead of guessing. No Phase 2
feature code, permissions or migrations have been applied. Phase 2 acceptance is
0/8; preparation only. Recommended answer: audited operator publication with
read-only tenant access; tenant administrators retain only tenant-scoped writes.

Q-003 resolved by user: audited operator publishing, global tenant reads only.
ADR-0007 accepted; Phase 2 implementation proceeds.

### Phase 2 implementation and local validation
ADR-0007 accepted after the explicit operator-only publishing decision. Implemented
P2-01 through P2-07 vertical slices, typed API/UI and reversible empty migrations.
Core remains industry-neutral. Direct memberships and department grants are
independent; tenant revocation preserves history and removes effective grants.
Database protection covers immutable definitions, stable identities and membership
history. Global reference publication is audited and has no tenant write endpoint.
Imports are bounded, atomic, formula-safe and preview/hash guarded. A regression
test verifies untrusted XLSX dimensions cannot silently discard actual rows/cells.

Local fail-fast gates PASS: 63 backend tests, zero skips; 5 frontend tests; Ruff
lint/format; strict mypy Windows/Linux (153 files); migration roundtrip/drift;
OpenAPI drift; frontend lint/types/build. Real Chromium/Keycloak login exercises
workspace/project/group/master-data creation and import/export.
Hosted acceptance remains pending. P2-01 through P2-08 are not finally marked pass
until the implementation commit's hosted checks pass.

Deferred to owning phases: forms (3), workflow/milestones (4), tasks (5), automation
and integrations (6), large asynchronous transfer/reporting jobs (7), pack registry
and industry definitions (8), production deployment/load/legacy cutover (10).
No deferred Phase 2 acceptance requirement and no unresolved security blocker.

### Phase 2 final acceptance
Hosted run: https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37350474988
Code commit: `5c0d19b`. Backend and frontend jobs PASS.
P2-01 through P2-08 PASS (8/8): project lifecycle/audit; departments/teams;
independent scoped membership/grants; governed typed master data; safe atomic
imports/paged exports; relational/history/migration protection; typed API/UI;
all local and hosted quality gates, ADR/runbook/changelog/progress evidence.
Local suite: 63 backend tests with no skips and 5 frontend tests. Hosted Linux
passes non-browser and real Keycloak browser tests, lint/types/build, migration
upgrade/drift and generated OpenAPI/TypeScript drift.
No Phase 2 deferred acceptance item. Future-phase work remains assigned above.
Phase 3 not started; final acceptance is committed after code-head CI succeeds.

## 2026-10-05 - Phase 3 preparation
Sources: docs/02,03 FR-020 through FR-026 and FR-040 through FR-042/045/046,
05-09,13-14,17-22,25-28. Phase 2 accepted before starting.
Acceptance criteria written before feature implementation:
- P3-01: Typed sections/component contracts cover V1 families and reusable version-pinned
  fields/components/forms; publishing resolves references into a validated snapshot.
- P3-02: Draft editing uses optimistic concurrency; publish preview/apply validates
  and freezes exact versions; deprecated/retired versions preserve historical use.
- P3-03: Bounded declarative AST evaluates defaults/visibility/requiredness/formulas,
  rejects unsafe operators, unknown references and cycles; no arbitrary execution.
- P3-04: Authoritative exact-version validation, scoped lookups and component permissions;
  drafts/autosave and immutable submitted snapshots with idempotency/audit.
- P3-05: Private scoped attachments, content/size validation, fail-closed scanning hook,
  short-lived downloads and tenant/ownership authorization with negative tests.
- P3-06: Accessible Form Studio palette/structure/properties/preview/history/publish and
  runtime component families, visible errors and scoped administration.
- P3-07: Tenant-safe migrations, database immutability/history protections, guarded rollback,
  unit/integration/API/browser tests covering isolation, formulas, uploads and versions.
- P3-08: Local and hosted tests/lint/types/build/contracts pass; ADR/runbook/changelog,
  four progress files and phase-oriented commits updated. No next phase before acceptance.
Workflow routing/approval and scheduling remain Phase 5/4 respectively, per docs/25.
Earlier Phase 2 log prose reversing those numbers is superseded by this correction.

### Phase 3 implementation and local validation
Implemented P3-01 through P3-07: typed component families and pinned libraries;
immutable versions with publication preview/hash and revision checks; bounded AST;
authoritative scoped runtime and defaults; autosave, signatures and immutable
idempotent submissions; private files with fail-closed scanning and short-lived
downloads; Form Studio; guarded migrations and isolation/history tests.
ADR-0008 records runtime, permissions, signature and attachment trust decisions.
Local gates PASS: 90 backend tests without skips, 7 frontend tests, Ruff,
strict mypy Windows/Linux (172 files), migration roundtrip/drift, OpenAPI drift,
frontend lint/types/build and real Keycloak browser publication/autosave/submission.
Hosted acceptance pending; none of the eight criteria is finally accepted yet.
No Phase 3 acceptance item deferred. Authoritative shift/approved-default providers
belong to Phase 4/5 through tested application ports; production scanner provisioning
and retention/quotas belong to Phase 10. Failed object cleanup reconciliation is
TD-005 for Phase 6. No legacy data migration or history deletion was performed.
