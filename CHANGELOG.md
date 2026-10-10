# Changelog

## Unreleased - Phase 6 in progress (2026-10-10)

- Require webhook delivery attempts to check the current endpoint head: endpoint
  edits preserve a rule's pinned version, while a later revocation blocks that pin.
  Focused security tests verify both behaviors before secret lookup/network access.

- Add authenticated organization/workspace webhook endpoint administration UI for
  registration, immutable versioning and revocation. Secret references are write-only
  from the UI and remain stored externally. Frontend checks pass; delivery remains
  fail-closed pending the deployment resolver and durable worker.

- Add a bounded direct HTTPS webhook transport foundation: validate all resolved
  addresses, pin TCP to a vetted IP while preserving TLS hostname checks, reject
  redirects, cap response bodies/timeouts and sanitize provider errors. Add deployment
  CIDR validation and a tenant/version secret-resolver contract. Fake transport and
  socket tests pass; outbound action/worker delivery remains fail-closed pending a
  deployment resolver and durable attempt ledger.

- Add audited organization/workspace/project scoped webhook endpoint version API
  under ADR-0026. Restrict `integration.manage` to existing administrator and
  project-manager roles at their granted scope. URL/secret-reference changes append
  versions; revoke appends a tombstone. Responses and audits omit secret references.
  Guarded migration, scope, stale-write, revoke and immutability integration checks
  pass. Webhook actions remain unavailable until the safe delivery worker is ready.

- Resolve webhook security boundary Q-009 under accepted ADR-0026. Add a typed
  identifiers-only event envelope, bounded canonical JSON, HMAC-SHA256 signature
  headers and HTTPS/DNS/address allowlist policy primitives. Five focused security
  tests pass. No network delivery is enabled pending scoped endpoint management,
  external secrets and a verified pinned-address HTTPS transport. Hosted
  [38059383470](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38059383470)
  passes both jobs on exact code 0f7e066f001196ee1d9851d42941ab513e688e95.

- Add controlled project append_tag/append_flag actions through the owning service
  under ADR-0025. Preserve first-append authorship/audit, exact kind/case distinctions
  and per-action receipts. Add fresh project authority, bounded scoped read/filter/
  page UI, immutable database guards and populated rollback refusal in e49b7d83af20.
  Labels are inert metadata; industry meanings belong in Domain Packs. All local
  gates pass (298 backend/18 frontend tests), including real PKCE and committed
  Redis/concurrent append coverage. Exact-code hosted verification is pending;
  Phase 6 remains unaccepted.

- Add distinct generic automation tasks through the owning task service under
  accepted ADR-0024. Preserve assignment snapshots and event-time due dates;
  support atomic claims and claimant-only audited completion in API/My Work.
  Form submissions and independent approval remain governed by their existing
  workflow. Migration d318af6c902e preserves form pins and refuses populated
  generic rollback. All local gates pass (285 backend/18 frontend tests), including
  real PKCE execution, committed Redis/claim/completion concurrency, lint/types,
  migrations and generated contracts/build. Hosted
  [38052949486](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38052949486)
  passes both jobs on exact code d25ad7a. Phase 6 remains unaccepted.

- Add organization-scoped email evidence and reviewed recovery API/UI under
  ADR-0023. Preserve original delegation, immutable attempts, exact review/reason
  and lifetime limits; require uncertain duplicate-delivery acknowledgement.
  Return no addresses/content/secrets, and distinguish provider acceptance from
  mailbox delivery. Add reversible chronological lookup indexes in ba6e379cc281.
  All local gates pass (272 backend/18 frontend tests, real PKCE browser and
  committed concurrent recovery, lint/types, migrations and generated contracts/
  build). Hosted
  [38049979000](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38049979000)
  passes both jobs on exact code b0b9d05. Phase 6 remains unaccepted.

- Add scoped automation rule/version administration and immutable run evidence
  API/UI under ADR-0022. Review exact saved content before activation; preserve
  pinned versions, fresh delegation, twenty-attempt limits and audit history.
  Public replay reviews run plus queue state and rejects stale/duplicate applies.
  No migration or retained-data rewrite. All local gates pass (261 backend/16
  frontend tests, real PKCE browser and committed concurrent replay, lint/types,
  migrations and generated contracts/build). Hosted
  [38047837127](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38047837127)
  passes both jobs on exact code fe4ebc8.
  Phase 6 remains unaccepted.

- Add explicit transactional email capture for verified-email invitations and
  activated notify action channels under ADR-0021. Expose invitation opt-in/reason
  in the typed API/browser form. Email-only rule notices retain minimal immutable
  evidence while inbox/detail/read stay private. Preserve manual defaults and
  automatic in-app projections. Add guarded migration `5caef6ad5721`, source
  rollback/dedup tests, real browser opt-in and rule-to-Redis-to-loopback-SMTP checks.
  All local gates pass (250 backend/14 frontend tests, lint/types, migrations and
  generated contracts/build). Hosted
  [38044650329](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38044650329)
  passes both jobs on exact code 6fd5082, including real PKCE browser opt-in,
  committed concurrency, Redis/loopback SMTP delivery and migrations;
  Phase 6 remains unaccepted.

- Implement explicit scoped SMTP queue/worker/dispatch and reviewed replay under
  ADR-0020. Preserve source IDs, fresh authority, immutable attempt/audit evidence,
  bounded retries and stable Message-ID. Expired claims become uncertain without
  automatic resend. Tenant profiles remain external secrets; tests use fake or
  loopback SMTP only. Add guarded additive migration `208f826ca492`. Automatic
  email capture/action channels and other Phase 6 requirements remain open.
  All local gates pass: 240 backend and 14 frontend tests, Ruff/strict types,
  migration round-trip/drift and generated contracts/build. Hosted
  [38042281045](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38042281045)
  passes both jobs on exact code ee70500, including browser/committed workers,
  Linux quality gates and migrations. Phase 6 remains unaccepted.

- Accept ADR-0019 under the user's delegated choice: token-free verified-email
  invitations with idempotent creation, fresh scoped inviter authority, exact
  OIDC-verified recipient email, seven-day expiry and one-time acceptance.
  Add typed API/client and browser link/PKCE acceptance, preserving existing token
  invitations. Guard immutable invitation binding and history, with token-only
  reversible migration and populated new-mode rollback refusal. SMTP delivery
  and recovery remain required Phase 6 work; links are currently shared manually.
  All local gates pass (227 backend/14 frontend), including real PKCE acceptance,
  concurrent retries, immutable binding and guarded rollback. Fix an unordered
  administrator test fixture exposed by Linux CI; 46 affected tests pass locally.
  Hosted [38036138271](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38036138271)
  passes both jobs on final code 82cf4e5, including Linux tests/types, browser and
  committed concurrency, migrations and generated contracts.

- Add bounded preview/apply reconciliation for historical workflow notify and task
  reminder handoffs (ADR-0018). Preserve original source/audit/read history; create
  current operator evidence and notification-only deliveries for missing exact
  intents, and leave existing handoffs intact. Add reversible lookup indexes.
  Verify 215 backend/11 frontend tests and all local gates, including 104-intent
  pagination, atomic rollback and committed duplicate capture/delivery.
  Hosted run 37519811189 passes both jobs on exact code 079b8c8, including Linux
  gates, real browser/worker flows, duplicate handoffs/delivery and migrations.

- Add reviewed, audited notification replay through a scoped operator command
  (ADR-0016). Requeue the same failed delivery under fresh administrator authority;
  reject stale reviews, preserve source/recipients/attempt/read history and enforce
  the twenty-attempt cap. Historical handoff reconciliation and management API/UI
  remain Phase 6 work.
  Verify 203 backend/11 frontend tests and all local gates, including committed
  duplicate requeue and forced tenant/identity lock contention.
  Hosted run 37514426474 passes both jobs on exact code ffac30f, including Linux
  types/tests, real browser/worker flows, committed concurrency and migrations.
- Repair tenant/user lock inversion using an organization-owned application contract
  (ADR-0017), preserving fresh authorization and revocation serialization.

- Add a scoped automatic in-app consumer for task assignment/deadline/reminder and
  workflow review/notify sources, immutable attempt/skip evidence, bounded retries
  and persisted-consumer worker routing (ADR-0015). Recheck original and live
  recipients; preserve notice history after project closure and guard rollback.
  Historical handoff reconciliation, controlled replay and email/invitations remain
  current Phase 6 requirements.
  Verify 195 backend/11 frontend tests and all local gates, including real Redis
  duplicate delivery, concurrent read receipts and guarded migration rollback.
  Hosted run 37511023333 passes both jobs on exact code 2cebf5e, including Linux
  tests/types, real PKCE browser, worker, migration and contract gates.

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
