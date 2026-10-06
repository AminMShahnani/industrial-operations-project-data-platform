# Changelog

## Unreleased - Phase 6 in progress (2026-10-06)

- Add immutable, recipient-scoped in-app automation notices and read receipts,
  fresh source authorization, chronological paging and workspace inbox/API
  (ADR-0014). Preserve private drafts and roll back all effects on recipient failure.
  Verify 186 backend/11 frontend tests and all local gates; hosted run 37504095044
  passes both jobs on 11b7818, including real PKCE browser delivery/read.
  Email/automatic intents and remaining Phase 6 work are not accepted or deferred.

- Add bounded timer/deadline generation, exact timer-version matching, immutable
  occurrence evidence and scoped preview/apply CLI (ADR-0013). Preserve task
  lifecycle/private drafts and serialize duplicate ticks; populated rollback is guarded.
- Verify 178 backend/11 frontend tests and all local gates; hosted run 37499621510
  passes both jobs on 3beb19d, including committed periodic concurrency. Phase 6
  remains in progress with no phase advancement.
- Implement bounded tenant-private orphan reconciliation with explicit grace,
  fresh authority/reference checks, shared upload locks, immutable requested/result
  audits, conditional S3 deletion and resumable crash recovery (ADR-0012, TD-005).
- Resolve TD-005 after 166 backend/11 frontend tests and all local gates pass;
  hosted run 37480916988 passes both jobs on adea461. Phase 6 remains in progress.
- Record eight automation/notification acceptance criteria and ADR-0011.
- Add typed event/delivery contracts, bounded retry/causation rules and Dramatiq
  transport with five tests, including real Redis. Full local suite: 141 backend
  and 11 frontend tests pass.
- Accept Q-006 activating-administrator delegation in ADR-0011; recheck current
  identity and scoped permissions on execution and replay.
- Add guarded durable outbox, immutable rule versions, pinned runs/attempts/receipts,
  atomic source-audit capture, bounded retries and audited replay/dispatch services.
- Verify 148 backend and 11 frontend tests plus lint/types/build/contracts locally.
  Production action handlers, workers and notifications remain in progress;
  Phase 6 remains unaccepted (0/8).
- Add authorized metadata/related-record/form-task/pinned-workflow actions and a
  durable savepoint-based automation consumer, Dramatiq actor and scoped dispatcher.
- Verify atomic rollback/retry, source privacy, target scope and concurrent actual
  Redis worker deduplication. Local suite: 156 backend and 11 frontend tests pass.
  Remaining Phase 6 adapters, notifications, triggers and UI stay in progress.

## Unreleased - Phase 5 complete (2026-10-06)
- Accept mandatory independent approval in ADR-0010; administrators cannot self-approve.
- Add typed bounded workflow graphs and one/all/quorum/sequential approval invariants.
- Add scoped definition/version persistence with immutable activation and guarded rollback.
- Add assigned workflow actions, immutable correction/amendment links, task state
  integration, authoritative approved defaults and scoped administration/review UI.
- Add runtime evidence guards and Reviewer/Approver project role migrations.
- Phase 5 accepted: 8/8 criteria, 136 backend and 11 frontend tests; local and
  exact-head hosted gates pass on d91dfce / run 37454353238.

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
