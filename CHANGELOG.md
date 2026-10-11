# Changelog

## Phase 8 complete (2026-10-11)

- Add typed schema-versioned Domain Pack manifests, generated JSON Schema, bounded
  safe package validation, a read-only curated registry adapter, deterministic
  dependency resolution, SDK validation, review-only typed migration descriptors
  (ADR-0036), and organization-scoped plan/apply lifecycle API/UI under ADR-0035.
  Install/upgrade is preview-bound, permission-checked, audited and provenance
  preserving. Template artifact materialization and safe uninstall remain deferred;
  accepted ADR-0037 defers template-specific semantic validation until stable artifact
  schemas and reference conventions are defined.

- Phase 8 local acceptance: 362 DB-backed backend tests and 9 browser tests pass;
  frontend tests/build, lint, strict type checks, generated schemas/contracts and
  migration upgrade/rollback/drift checks pass. Populated installation history
  rollback refusal is covered by API integration. Exact hosted run
  [38141929240](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38141929240)
  passes both jobs on `d87d3a76d46449366766a666900fff6f098206f1`; Phase 8 is accepted
  8/8.

## Unreleased - Phase 9 implementation pending hosted acceptance (2026-10-11)

- Define P9-01..08 acceptance criteria for typed Oil & Gas pack artifacts,
  explicit workspace/project imports, draft-only workflows, governed KPIs and
  declarative mappings. Q-018 and Q-019 are resolved in ADR-0038/0039. Add typed
  artifact envelopes, exact cross-artifact references, generated JSON Schema and
  package-level expression/reference/cycle validation. Publish curated Oil & Gas
  1.0.0 with 13 form templates, 16 master-data types, four inactive workflow
  templates, three inactive automation examples, seven KPI definitions and three
  internal mapping profiles. Add preview-bound workspace imports of forms,
  master-data types and workflows through owning services, with per-type authorization,
  idempotency, persisted provenance and audit. Add KPI definitions as private saved
  reports pinned to exact published form versions; enforce scoped `submission.read`,
  identity-free aggregate projections and a 366-day maximum. Keep automation examples
  inert and mapping profiles typed, internal and transform-free. The Admin UI exposes
  authorized KPI results and dashboard units. Fix nondeterministic XLSX modified-time
  metadata so repeated exports are byte-identical.

- Phase 9 local verification: 383 backend tests pass (9 opt-in tests skipped), the
  isolated real OIDC/PKCE browser test passes, and frontend lint/typecheck, 19 tests
  and production build pass. Strict mypy (333 files), Ruff check/format, OpenAPI and
  artifact-schema drift, curated package validation, and isolated migration roundtrip/
  Alembic drift pass. Exact-code hosted CI remains before phase acceptance.

## Phase 7 complete (2026-10-11)

- Add creator-private durable report export jobs for CSV/XLSX/PDF. Jobs bind to
  immutable report versions, use current dataset authorization at generation and
  authenticated download, verify artifact size/digest, and recover pending/stale work
  through an ID-only worker dispatcher. Private artifacts are cleaned up after the
  24-hour retention window accepted in ADR-0034 (Q-014 resolved).
  Add paginated text-only PDF output and export-job status/download UI.
- Guard export-job rollback when retained job history exists and add a separate
  reversible recovery-index migration. PostgreSQL coverage verifies private job
  visibility, version pinning, idempotent replay, PDF bytes, download integrity and
  populated rollback refusal.

- Phase 7 acceptance: 328 backend tests, 9 browser tests, 19 frontend tests, lint,
  strict types, OpenAPI drift and isolated migration gates pass locally. Hosted run
  [38130020096](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38130020096)
  passed both jobs on implementation commit `fedb956386855f324fa024f52347fe710c97e6ea`.

- Add explicit master-data CSV/XLSX header mapping under ADR-0032. Imports remain
  create-only; apply binds the source file, mapping digest and immutable type
  version, while unused columns can be skipped. The Admin flow now previews mapped
  values and issues before applying. Legacy canonical-header imports remain
  supported. API regressions and the real PKCE browser flow pass.
- Add a creator-private state-count bar dashboard widget sourced from the existing
  bounded state-grouped report. The accessible UI uses labeled native meters and
  introduces no new measure. Normalize XLSX document and ZIP timestamps for
  byte-stable repeated exports.
- Add creator-private trend and line widgets over a governed current-overdue count
  by UTC due-date week, under ADR-0033. Results contain the prior 12 week buckets
  (including zeros) and a bounded older bucket, computed by the Tasks service in a
  single query and exported as grouped CSV/XLSX. This is not historical state
  snapshot reporting.

- Add creator-private dashboard definitions under ADR-0030. Bounded layouts reference
  up to six of the owner's saved reports; table and overdue-list widgets recheck live
  dataset permissions at execution. Add audited immutable versions, archive state,
  scoped API and Admin UI, with guarded migration `8d77c0f21a46`. Focused PostgreSQL
  reporting/dashboard tests and the real PKCE browser create/run/archive flow pass.
  This is an initial widget slice; the full backend regression and hosted exact-code
  verification remain pending, and P7-03 is not yet accepted.
- Add stable ascending/descending task-ID sorting to saved reports, with matching
  cursor predicates in the Tasks query and browser authoring controls. Full local
  backend regression passes (323 tests; 9 e2e tests excluded), with frontend tests,
  lint, types and production build passing. P7-02 remains incomplete.
- Add filtered overdue-task counts grouped by state under ADR-0031. The Tasks module
  computes bounded-cardinality aggregates independently of the row page; grouped
  output excludes task identities and is rendered in saved-report and dashboard
  results. PostgreSQL and PKCE browser coverage pass; P7-02 remains incomplete.
- Add status-distribution and total overdue-count dashboard widgets. Both require a
  state-grouped saved report and recheck its current access; API tests cover bounded
  results and incompatible definitions. Trend/bar/line shapes remain Phase 7 work.
- Connect the saved-report editor to versioned updates. Owners can load, change and
  save bounded definitions using expected-version concurrency; the PKCE browser flow
  covers create, update, run, dashboard status view and archive.
- Add creator-authorized CSV/XLSX saved-report downloads. Each request rechecks current
  dataset access, exports only selected fields, caps output at one 100-row page and
  prevents user text from becoming spreadsheet formulas. PDF and durable large exports
  remain Phase 7 work.
- Add creator-private, bounded saved report definitions for overdue tasks with
  immutable audited versions, optimistic updates, archive state, current permission
  checks on each run, and create/list/run/archive controls in the browser. The authoring
  form selects bounded state filters and output columns. Add guarded
  migration `41a9c1d7e5b0`, empty rollback/reapply and populated rollback tests, and
  update the Phase 6 audit-key round-trip order for Phase 7 tenant-linked FKs. The
  full backend regression passes (315 passed, 9 optional skips); the added migration
  cases pass in the focused database suite, and the real PKCE browser flow passes
  through saved report create/run/archive. Ruff, strict mypy, OpenAPI drift and
  frontend lint/types/tests/build pass. Dashboards, durable exports and transfer jobs
  remain active Phase 7 work; no phase criteria are accepted yet.
- Add an authorized aggregate overdue-task scope using current `schedule.manage`
  permissions (ADR-0028); keep recipient/claimant identifiers out of the projection.
  The browser offers personal and workspace views, and API/browser tests cover manager
  success and Viewer denial. Resolve saved-report ownership as creator-private under
  ADR-0029 (Q-011). Local DB suite (314 tests), browser flow, frontend checks, types,
  lint and contract generation pass; hosted verification is pending.
- Add the first Phase 7 governed dataset endpoint for a caller's overdue tasks,
  delegated to the task service's existing scoped personal query and returning a
  100-row-capped minimal projection. Add a PostgreSQL integration test for assignment
  privacy and a service projection unit test. Add a browser view for the selected
  workspace with accessible table semantics and cursor pagination. Frontend lint,
  typecheck, 19 tests and build pass. Cross-user aggregates, saved reports, dashboards
  and export/import jobs remain unimplemented pending their contracts. The opt-in PKCE
  browser test checks successful report loading and the empty state. Hosted backend
  run 38081888097 exposed a test fixture using the wrong principal; corrected to use
  the workspace admin, with the full DB-backed suite and browser test passing locally.
  Exact-code hosted run 38083622954 passes backend/frontend gates. Owner accepts and
  verifies this slice; no Phase 7 criteria are accepted yet.
- Accept Phase 6 P6-01 through P6-08 after local quality gates, exact hosted run
  38079026238 on `b97822eb136c47946b6a1252149abc64fbf09f4b`, and project-owner
  verification of deployment secret-mount isolation and network egress controls.
- Define Phase 7 reporting/export/import acceptance criteria and record 0/8 accepted.

- Add tenant-scoped webhook delivery history and reviewed replay with state/attempt
  hash previews, fresh operator and original-delegator authority, reasoned audit, and
  explicit acknowledgement for uncertain duplicate risk. Expose bounded delivery
  history without URLs, secret references, payloads or key bytes in API/UI. Dispatch
  expired sending leases so they become uncertain rather than remaining stuck.
- Add ADR-0027's mounted external secret-store adapter with strict tenant/reference/key
  version binding, redacted missing/malformed errors, symlink/type/size checks and
  fail-closed worker wiring. Add interval dispatcher mode and bounded structured
  outcome logs. Reconcile webhook endpoint audit foreign keys to tenant-composite
  linkage in migration `fc5310a0d279`; `ee31ac92bf10` remains the guarded delivery
  ledger migration. Backend (312 tests), PKCE browser recovery, frontend (19 tests),
  lint/types/build, local PostgreSQL upgrade/drift, migration round-trip, and API/client
  generation pass. Secret mount and network egress policy remain deployment gates;
  exact hosted-code verification and Phase 6 acceptance are pending.

- Persist each webhook intent with an audited pending state, and add immutable
  attempt evidence guarded by exact audit linkage. A separate Dramatiq actor claims
  leases, sends only identifiers-only signed envelopes using the pinned HTTPS
  transport, and records bounded outcomes; expired claims become uncertain. Add
  an ID-only due-intent publisher and an unconfigured secret resolver that fails
  before claiming, so no attempts are consumed before deployments inject their
  tenant-isolated secret manager. Migration ee31ac92bf10 refuses populated rollback.
  The previous full backend regression passed (310 passed, 9 optional skips); this
  follow-up's expanded checks are recorded in the Phase 6 log before acceptance.

- Require webhook delivery attempts to check the current endpoint head: endpoint
  edits preserve a rule's pinned version, while a later revocation blocks that pin.
  Focused security tests verify both behaviors before secret lookup/network access.
  Hosted run 38066369565 passes both jobs on exact code a9843addf6484edd0aebf10a098c9b7cb273e259.

- Add authenticated organization/workspace webhook endpoint administration UI for
  registration, immutable versioning and revocation. Secret references are write-only
  from the UI and remain stored externally. Frontend checks pass; delivery remains
  fail-closed pending the deployment resolver and durable worker. Hosted run
  38065351280 passes both jobs on exact code f0c13473762d5452179fab58c2a90ebc326e7652.

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
