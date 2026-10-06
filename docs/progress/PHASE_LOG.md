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

### Phase 3 final acceptance
Code commit: fad771b. Hosted run:
https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37363436134
Both backend and frontend jobs PASS on that exact commit.
P3-01 PASS: typed component families, sections and immutable pinned libraries.
P3-02 PASS: optimistic draft edits, publication preview/hash and version lifecycle.
P3-03 PASS: bounded safe AST, dependencies, defaults and cycle rejection.
P3-04 PASS: exact-version scoped runtime, privacy, autosave, signatures and idempotency.
P3-05 PASS: private attachments, content/size/scanning checks, signed scoped downloads.
P3-06 PASS: Form Studio builder, preview, versions and submission runtime.
P3-07 PASS: composite ownership, database immutability, guarded migrations and tests.
P3-08 PASS: all local/hosted quality gates, ADR/runbook/changelog/progress evidence.
8/8 accepted; no Phase 3 acceptance item deferred. Future dependencies and TD-005
remain assigned above. Overall 4/11 phases accepted. Phase 4 has not started.

## 2026-10-06 - Phase 4 preparation
User requested Phase 4. Read AGENTS.md first, then docs/00 through docs/28 in
numeric order; reviewed accepted ADRs, operations guidance, module boundaries,
progress and current application interfaces. Phase 3 is accepted on fad771b;
acceptance records are committed/pushed as 91b42bc. Initial working tree clean.
Sources: docs/03 FR-030 through FR-034; docs/05-09,11-12,14,17-23,25-28.
Acceptance criteria written before Phase 4 feature implementation:
- P4-01: Typed, tenant-scoped schedule/version and assignment contracts pin exact
  published form versions. Activation/version changes use validated preview,
  concurrency checks, immutable definitions and audit; historical tasks remain intact.
- P4-02: Bounded one-time, interval, calendar/RRULE and shift recurrence; scoped
  milestone/relative-event inputs; explicit timezone and UTC persistence. DST gaps,
  overlaps, month boundaries and invalid/unbounded rules have deterministic tests.
- P4-03: Rolling-horizon generation/extension is idempotent under retries and
  concurrent execution, with database uniqueness on schedule/version/time/assignment
  scope. Deterministic recipient snapshots never grant new workspace/project access.
- P4-04: Authorized task claim/start/cancel/supersede and exact-version submission
  linkage preserve ownership/history. Concurrency, revoked access and cross-scope
  attacks are tested. Workflow-only review/approval actions remain Phase 5 authority.
- P4-05: Cursor-paged personal/team/department/project inboxes expose due today,
  overdue and upcoming work, with scope checks and UTC/timezone-correct filters.
  Returned/waiting-review views use lifecycle contracts without inventing approvals.
- P4-06: Idempotent due/overdue reminder records are visible in-app; documented
  periodic execution extends horizons and reminders with tenant context. Phase 6
  notification delivery consumes a typed handoff; email is not claimed in Phase 4.
- P4-07: Accessible scheduling administration and My Work connect to form runtime;
  authoritative shifts connect through the Phase 3 DefaultContext application port.
  Tenant-safe migrations, history protection and guarded rollback are tested.
- P4-08: All unit/integration/API/browser tests, migrations, lint/type/build and
  generated contract checks pass locally and in hosted CI. ADR/runbook/changelog,
  all progress files and phase-oriented commits contain evidence and deferrals.
0/8 accepted. No implementation, migration or new framework introduced yet.
Q-004 is pending: shared claim versus per-recipient completion for group targets.
ADR-0009 records this unresolved ownership/security boundary. Do not guess it.
Phase 5 has not started; no Phase 4 requirement is silently deferred.

### Phase 4 assignment decision resolved
User selected the recommended shared occurrence with one atomic claimant on
2026-10-06. Q-004 resolved; ADR-0009 accepted. Every action rechecks live scoped
permissions; assignment snapshots grant no access and private drafts remain owned
by the claimant. Typed contracts and migrations now precede feature implementation.

### Phase 4 implementation and targeted validation
Added typed schedule/version/assignment/recurrence/shift/trigger/task/reminder
contracts and guarded b71acf0449b2 migration before application slices. Version
activation is preview/hash/revision guarded. Active definitions and recipient
snapshots are immutable; history deletion/truncation and populated rollback deny.
Generic milestones remain project-owned; shift defaults use the trusted Phase 3 port.
Implemented bounded timezone/DST recurrence, deterministic snapshot recipients,
idempotent generation, atomic shared claims and private drafts. Exact submission
updates its task in the same transaction. Added My Work, version administration,
in-app reminders and scoped periodic CLI. No industry semantics added to Core.
Targeted results: 13 recurrence tests, 8 API tests, 9 frontend tests and the real
PKCE browser flow pass. Browser exercises concurrent generation/claim retries,
autosave and immutable task submission. Complete local/hosted gates pending;
0/8 finally accepted. Phase 5 has not started.

Full local gates PASS: 111 backend tests, zero skips; 9 frontend tests; Ruff,
strict mypy Windows/Linux (184 files), migration roundtrip/drift, OpenAPI drift,
frontend lint/types/build. Browser proves concurrent real HTTP materialization,
claim idempotency and transactional exact-version submission. Final live group/role
authorization checks added after that run; targeted revalidation pending. Hosted
acceptance pending. No Phase 4 acceptance criterion deferred. Email/queue delivery,
workflow approval/actions and production deployment retain their Phase 6/5/10 owners.

Final targeted revalidation PASS: all 8 Phase 4 API cases including tenant user
revocation, removed-team-member denial, cancellation and exact task submission;
strict mypy, Ruff and frontend lint/types pass. Generated OpenAPI remains in sync.

### Phase 4 final acceptance
Code commit: d92a10f. Hosted run:
https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37432881526
Backend and frontend jobs PASS on that exact commit, including Linux non-browser
tests, real Chromium/Keycloak concurrency/task runtime, migrations and contract drift.
P4-01 PASS: scoped typed schedules, exact form pins, immutable version activation.
P4-02 PASS: bounded recurrence, shifts/events/milestones and deterministic DST/calendar rules.
P4-03 PASS: rolling generation, deterministic snapshots and concurrent database idempotency.
P4-04 PASS: atomic claims, fresh authorization, private drafts and exact transactional submission.
P4-05 PASS: cursor-paged scoped My Work and timezone-correct derived status views.
P4-06 PASS: idempotent in-app reminders and reproducible scoped periodic execution.
P4-07 PASS: accessible scheduling/task runtime, authoritative shift defaults and guarded migrations.
P4-08 PASS: all local/hosted gates, ADR/runbook/changelog/progress and phase commits.
8/8 accepted. Local suite: 111 backend tests without skips, 9 frontend tests;
Ruff, strict mypy Windows/Linux (184 files), migration roundtrip/drift, OpenAPI drift,
frontend lint/types/build. No Phase 4 acceptance item deferred. Approval/workflow,
email/queue delivery and production deployment remain Phase 5/6/10 responsibilities.
Documented recurrence/recipient/generation/supersession bounds remain intentional.
Overall 5/11 phases accepted. Phase 5 has not started.

## Phase 5 preparation - 2026-10-06
Read AGENTS.md first and numbered docs in order; reviewed docs/10 and existing
Phase 4 composition/progress. Phase 4 remains accepted on d92a10f, hosted run
37432881526. Sources: docs/03,05,07,09-12,17-22,25-28.
Acceptance criteria before Phase 5 implementation:
- P5-01: Scoped definitions and immutable activated workflow versions validate
  start/review/approval/decision/notify/end graphs and typed assignment policies.
- P5-02: Submitted records start instances pinned to exact workflow/form versions;
  routing, retries and concurrent actions are transactional and deterministic.
- P5-03: Assigned review/approval enforces fresh server authorization, tenant and
  project isolation, independent-approval policy once resolved, and one/all/quorum/
  sequential completion. Unauthorized and stale actions fail without side effects.
- P5-04: Return/reject/resubmit and governed corrections/amendments preserve prior
  snapshots, evidence, actor/reason history and immutable audit events.
- P5-05: Trusted workflow application contracts update task review/return/approval
  states and supply authoritative previous-approved defaults without table coupling.
- P5-06: Accessible assigned-action inbox and review administration show permitted
  evidence, action reasons, status and audit/history; private drafts remain private.
- P5-07: Scoped migrations, immutability/concurrency constraints and documented
  populated rollback safeguards pass integration tests; durable notification intents
  hand off to Phase 6 without prematurely selecting its worker framework.
- P5-08: Unit/integration/API/browser tests, migrations, lint/types/build and generated
  contracts pass locally and in hosted CI; ADR/runbook/changelog/progress and
  phase-oriented commits provide acceptance evidence and explicit deferrals.
0/8 accepted. Q-005 is pending; ADR-0010 proposed. No Phase 5 feature code or
migration introduced. No Phase 6 work started.

### Phase 5 approval authority resolved
User accepted recommended independent approval on 2026-10-06. Q-005 resolved;
ADR-0010 accepted. Approval authority is checked server-side and administrators
cannot approve their own submissions. Implementation begins with typed contracts.

### Phase 5 definition foundation checkpoint
Implemented typed workflow graphs, assignments, policies, definitions/versions and
runtime contract shapes. Pure domain validation enforces bounded reachable graphs,
explicit decision branches, separate return targets and no forward cycles. Approval
policies support one/all/quorum/sequential; submitter exclusion and distinct voter
identity preserve independent approval. No workflow API/runtime is exposed yet.
Added workflow-owned persistence and migration e049d194ba38 with composite scope
keys, exact scoped form pins, optimistic revisions, immutable activated content,
history deletion/truncation refusal and populated downgrade refusal. Tested tenant/
workspace isolation, stale writes, immutable versions and guarded rollback.
Local checkpoint gates: all 122 backend tests pass without skips, including existing
real PKCE browser and migration roundtrip; Ruff and strict mypy (190 files) pass;
OpenAPI drift and Alembic drift pass. Frontend gates are being rechecked.
This is a foundation checkpoint, not Phase 5 acceptance. P5-01 through P5-08 remain
unaccepted (0/8). Audited administration/activation, persisted runtime/actions,
resubmission/amendments, task/default integration, inbox/UI and hosted acceptance
remain required. Phase 6 has not started. Runbook describes guarded rollback.

Frontend checkpoint gates PASS: lint, strict TypeScript, all 9 tests and production
build. Local foundation checks complete; hosted results pending. Phase 5 stays 0/8.

### Phase 5 runtime verification - 2026-10-06
Foundation commit 554b593 passes hosted run 37442996936. Current uncommitted slice
adds audited administration, immutable activation, deterministic routing, assigned
independent review/approval, correction/amendment links, task state integration,
approved defaults, scoped evidence/history UI and bounded paging. Migrations add
runtime/revision/evidence guards and Reviewer/Approver project grant constraints.
Targeted tests: 16 pass (graph, persistence and five API cases), including private
draft denial, fresh grant revocation, rollback on empty approvers, pinned-version
resubmission, immutable evidence and approved-default isolation. Frontend types and
strict backend types pass. Separate real PKCE browser flow is under verification.
P5-01 through P5-08 remain unaccepted until complete local/hosted gates. No Phase 5
requirement deferred and no Phase 6 implementation started.

Final local runtime gates: 136 backend tests pass without skips in 93.81 seconds;
11 frontend tests pass. Separate real PKCE identities exercise return/correction
and concurrent idempotent approval. All assignment strategies except unsupported
manager context are exercised; live team/department/project revocation denies
actions. One/all/quorum/sequential policies, review routing, 156-action history
paging, preserved versions/defaults and immutable evidence pass. Ruff lint/format,
strict mypy Windows/Linux (202 files), migration and OpenAPI drift, frontend
lint/types/build pass. Final negative-scope/populated-role guards are revalidated
before commit. Hosted acceptance remains pending; no phase advancement.

### Phase 5 final acceptance - 2026-10-06
Code commit: `d91dfceabeeb0906395d57e42805e235c8d5f5e4`.
Hosted run: https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37454353238
Backend and frontend jobs PASS on that exact commit. Local full suite: 136 backend
tests without skips; final targeted API/browser revalidation: 15 pass in 59.19s.
Frontend: 11 tests. Ruff lint/format, strict mypy Windows/Linux (202 files),
TypeScript/ESLint, production build, empty migration roundtrip, populated rollback
guards, Alembic drift and generated API/client drift pass.

- P5-01 PASS: typed scoped definitions, graph validation, immutable exact-form pins
  and reviewed content-hash activation; one active binding per form version.
- P5-02 PASS: atomic submission startup, pinned immutable routing, deterministic
  decisions/notification intents and concurrent authenticated idempotent actions.
- P5-03 PASS: independent one/all/quorum/sequential approval, review roles, all
  supported assignment strategies, fresh group/project authority and scope denial.
- P5-04 PASS: return/reject routes, new correction/amendment drafts, pinned retired
  workflow resubmission and immutable payload/signature/action/audit history.
- P5-05 PASS: typed application ports update proven task states without rewriting
  root linkage and provide exact-scope/owner/form previous-approved defaults.
- P5-06 PASS: scoped administration, actionable inbox, permitted evidence/history,
  reasoned actions and owner revisions; private drafts stay private.
- P5-07 PASS: composite ownership/evidence constraints, bounded paged history,
  immutable notification handoff and empty/populated migration safety checks.
- P5-08 PASS: complete local and exact-head hosted gates, accepted ADR-0010,
  runbook/changelog/progress and phase-oriented implementation/acceptance commits.

8/8 accepted; overall 6/11 phases accepted. No Phase 5 acceptance item deferred.
Notification workers/email/timer automation remain Phase 6; configurable signatures
remain V1.5; deployment/load/backup validation remains Phase 10. Unsupported manager
relations fail explicitly under the documented where-supported assignment profile.
No industry-specific Core behavior or new execution framework. Phase 6 unstarted.

## Phase 6 preparation - 2026-10-06
Read AGENTS.md first and numbered docs in numeric order. Sources: docs/03-07,
10-12,16-23,25-28. Phase 5 retains 8/8 acceptance; overall 6/11 accepted.
Acceptance criteria before implementation:
- P6-01: Scoped typed rule definitions and immutable activated versions, validated
  declarative conditions/action schemas and audited preview/activation.
- P6-02: Atomic typed outbox events for supported operational triggers, durable
  bounded dispatch/consumption and deterministic causation/loop protection.
- P6-03: Approved execution authority, fresh target/recipient authorization and
  industry-neutral action services; no governance bypass or arbitrary code.
- P6-04: Durable runs/attempts/action receipts, retries/backoff, dead letters and
  audited scoped replay; crash/concurrent duplicate processing is idempotent.
- P6-05: Scoped in-app notifications and email adapter, existing task/workflow
  intents, authorized invitation delivery and explicit uncertain SMTP outcomes.
- P6-06: Accessible scoped rule/run/notification UI, current authority enforcement
  and safe bounded history; private operational data is not leaked through notices.
- P6-07: Reproducible worker/periodic execution, queue/run telemetry, TD-005 orphan
  reconciliation and guarded migrations/rollback/replay operations runbook.
- P6-08: Full unit/integration/API/browser/worker tests, migrations, lint/type/build
  and contracts pass locally/hosted; ADR/progress/changelog and phase commits.
0/8 accepted; no Phase 7 implementation. ADR-0011 selects Dramatiq/Redis with a
PostgreSQL durable ledger. Q-006 proposes activating-administrator delegated
authority with fresh scope checks; dependent writes await user resolution.

### Phase 6 safe foundation checkpoint
Added strict event/context and scoped ID-only delivery contracts; deterministic
consumer identity, bounded exponential backoff and causation cycle/depth rejection.
Locked Dramatiq 2.2.1 and tested its transport with stub and actual isolated Redis.
Business retries will be owned by PostgreSQL rather than broker automatic retries.
No automation action, authority bypass, notification/email delivery or public
worker endpoint is enabled. No schema migration yet; head remains 71db385e7a02.
Local gates: 141 backend tests pass without skips in 91.50s; 11 frontend tests;
Ruff lint/format, strict mypy (207 files), frontend lint/types/build, Alembic and
OpenAPI drift pass. Phase 5 acceptance-document run 37455189713 also passes.
P6-01 through P6-08 remain 0/8; remaining work is not deferred or accepted.
Q-006 remains pending and must resolve before dependent governed writes.

Foundation code commit 66a321a55c12766d004567f168490d4c3d51a57d passes hosted run
https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37456658887
Both jobs pass, including Linux strict mypy, real Redis transport, existing PKCE
browser flows, migrations and contracts. Phase 6 remains 0/8; Q-006 pending.

### Phase 6 authority resolved - 2026-10-06
User selected the recommended activating-administrator delegation. ADR-0011
accepted; Q-006 resolved. Proceed with immutable activated action scope, fresh
identity/permission/recipient checks on every run and replay, and retained evidence.
No implicit service-admin bypass, triggering-actor privilege inheritance or automated
approval. Phase 6 remains 0/8 while implementation and acceptance gates continue.

### Phase 6 delegated ledger checkpoint - 2026-10-06
Implemented scoped typed rule/version contracts, safe condition validation, immutable
activation with reviewed hash and organization-administrator delegation. Added
8323b0dbac0e: outbox events/deliveries, rules/versions, runs, attempts and receipts.
PostgreSQL guards protect evidence, version transitions, indexed envelope identity,
run scope/source/delegator binding and populated downgrade. Matching is pinned
atomically at source capture, with shared version locks and no activation backfill.
The composition root captures supported submission/project/master-data/workflow/task
source audits into the same transaction, with exact form pins and recipient IDs.
Application services implement fresh delegation checks, retained retirement semantics,
idempotent terminal runs/receipts, bounded retry and audited scoped replay/dispatch.
Production action/consumer implementations are still required; tests use a typed
executor fixture to verify authority and orchestration without sending messages.

Local verification: 148 backend tests without skips in 108.66s, 11 frontend tests;
Ruff lint/format, strict mypy on Windows/Linux (213 files), frontend lint/types/build,
OpenAPI drift, empty migration roundtrip/drift and populated rollback refusal pass.
P6-01 through P6-08 remain 0/8 until API/UI, all authorized action handlers,
worker/periodic consumers, notifications/invitations and TD-005 reconciliation pass
their acceptance gates. No remaining acceptance requirement is deferred to Phase 7.

Ledger code commit e1e84af7c04bd2a616c93d7e9ed256cd5b288ca2 passes hosted run
https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37462108788
Both backend/frontend jobs pass, including Linux types, real PKCE browser flows,
full migration roundtrip/drift and generated contracts. Development/test/browser
databases are at 8323b0dbac0e. Phase 6 remains in progress with 0/8 accepted.
