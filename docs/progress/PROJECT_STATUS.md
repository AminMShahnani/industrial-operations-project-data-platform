# Project Status

Status: PHASE 6 IN PROGRESS
Current phase: Phase 6 - automation and notifications
Last updated: 2026-10-10
Overall completion: 6/11 phases accepted. Phase 0 through Phase 5 each
satisfy 8/8 criteria. Phase 5: P5-01 through P5-08 PASS.
No unsupported project-wide percentage is reported.

## Completed modules
- Foundation, infrastructure, observability, CI and module boundaries.
- Identity, organizations/settings, workspaces, scoped IAM and immutable audit.
- Phase 2 implementation: projects/lifecycle, groups and scoped memberships/grants.
- Typed scoped master data, atomic imports, paged exports and operator publication.
- Typed API/client, scope-aware UI and migration/operations runbooks.
- Versioned forms/libraries, bounded expressions, Form Studio and scoped runtime.
- Autosave, immutable submissions/signatures and private fail-closed attachments.
- Immutable schedules, shifts and project milestones; bounded timezone-aware recurrence.
- Idempotent shared tasks, atomic claims, My Work and durable in-app reminders.
- Transactional task/submission linkage and scoped periodic generation CLI.
- Immutable workflow definitions, deterministic routing and independent approval.
- Preserved correction/amendment links, task transitions and approved defaults.
- Scoped assigned-action inbox, administration and immutable evidence/history UI.

## In progress
Phase 6 typed event/delivery contracts, bounded retry/causation rules and tested
Dramatiq transport. Durable outbox/rule/run persistence, transactional source capture,
delegated authority, receipts/attempts and replay application services are implemented.
Authorized project metadata, related-record, form-task and pinned workflow handlers
are implemented through owning services. A durable automation consumer, real
Dramatiq worker and scoped dispatcher are implemented and tested. Audited private
storage reconciliation is implemented and verified locally/hosted (TD-005).
Bounded scheduled timers and task due/overdue source generation are implemented
and verified locally/hosted; periodic evidence is immutable and task lifecycle stays intact.
In-app automation notices and their personal scoped API/inbox UI are implemented.
Automatic task/review/notify/reminder delivery, retry/skip evidence and shared worker
routing are implemented. Reviewed, audited notification replay is implemented through
a scoped operator command. Bounded reviewed historical notify/reminder handoff
reconciliation is implemented with exact intent provenance and notification-only
delivery. All local and exact-code hosted gates pass.
Verified-email invitation lifecycle/API/browser acceptance is implemented under
accepted ADR-0019, preserving old tokens and requiring verified recipient email
and current inviter authority. All local and hosted gates pass on final code
82cf4e5 / run 38036138271. Explicit scoped SMTP queue/dispatch/worker and reviewed
replay are implemented under ADR-0020, with immutable attempt evidence and guarded
migration 208f826ca492. All local gates pass (240 backend/14 frontend tests);
hosted run 38042281045 passes both jobs on exact code ee70500. Explicit transactional
invitation opt-in and immutable notify email channels are now implemented under
ADR-0021, including email-only evidence visibility and API/browser creation.
All local gates pass (250 backend/14 frontend tests); hosted run 38044650329 passes
both jobs on exact code 6fd5082. Task/workflow email uses explicit activated notify
rules; fixed
automatic in-app projections remain unchanged.
Scoped rule/run management and reviewed replay API/UI are implemented under
ADR-0022; all local gates pass (261 backend/16 frontend tests). Hosted run 38047837127 passes both jobs on exact
code fe4ebc8.
Email delivery/recovery API/UI is implemented under ADR-0023; all local gates pass
(272 backend/18 frontend tests). Hosted run 38049979000 passes both jobs on exact code b0b9d05.
Generic task creation, claim/completion API and My Work are implemented under
accepted ADR-0024; all local gates pass (285 backend/18 frontend tests), with
hosted run 38052949486 passing both jobs on exact code d25ad7a. Controlled project
tags/flags are implemented under ADR-0025, with scoped read/filter/page UI and
immutable audited first-append evidence. All local gates pass (298 backend/18
frontend tests); exact-code hosted verification is pending.
Webhook implementation awaits Q-009 / proposed ADR-0026, which documents the
network-egress and payload-disclosure boundary; the existing action remains
fail-closed. Tag/flag exact-code hosted verification is in progress. Telemetry and
remaining coverage are current-phase work. 0/8 accepted; Q-006 and Q-008 are resolved.
Phase 5 remains accepted on d91dfce / hosted run 37454353238.

## Blocked
None. Q-008 resolved: user accepted claimant acknowledgement under ADR-0024.
Generic tasks pass local/hosted gates; tags/flags pass local gates under ADR-0025
and await exact-code hosted verification.
Phase 6 remains 0/8 accepted.
Q-007 resolved on 2026-10-10: user delegated the choice with "do best".
ADR-0019 accepts token-free verified-email acceptance for new invitations,
preserving existing bearer-token invitations. Lifecycle passes local/hosted verification;
Scoped SMTP delivery/recovery and explicit source capture are verified.
Q-006 resolved: activating administrator delegates bounded scoped authority,
rechecked for every run/retry. ADR-0011 accepted. Q-005 resolved: independent
approval is mandatory, including administrators.
ADR-0010 accepted on 2026-10-06.
Q-004 resolved by user: shared task claimed by one eligible member.
Legacy export absent.

## Next 5 tasks
1. Finish controlled tag/flag exact-code hosted verification.
2. Resolve webhook egress and payload policy (Q-009); implement the accepted design.
3. Complete queue/run telemetry and operator failure visibility.
4. Complete remaining Phase 6 acceptance and fault/recovery coverage.
5. Verify all Phase 6 local/hosted criteria before any Phase 7 work.

## Test status
141 backend tests pass locally without skips, including separate real Keycloak PKCE
submitter/approver logins, concurrent approval retries, preserved corrections,
live group/project revocation and 156-action paged history. PostgreSQL migration
roundtrip/isolation, Redis and private S3 remain covered. 11 frontend tests pass.
Phase 6 adds five retry/loop/schema/broker tests, including real isolated Redis
delivery. Ruff lint/format and strict mypy Windows (207 files) pass; prior Phase 5
Windows/Linux strict types passed on 202 files.
Alembic drift, OpenAPI drift, frontend lint/types and production build pass.
Final targeted revalidation: 15 workflow API/browser tests pass in 59.19 seconds.
Hosted [37454353238](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37454353238)
passes backend/frontend jobs on exact code commit
`d91dfceabeeb0906395d57e42805e235c8d5f5e4`, including Linux tests, separate PKCE
identities, concurrent approval, migration and generated-contract drift.

Phase 6 foundation hosted [37456658887](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37456658887)
passes both jobs on `66a321a55c12766d004567f168490d4c3d51a57d`, including strict
Linux types, real Redis, prior browser flows and migration/contract checks. This
does not accept Phase 6 criteria. Q-006 is now resolved; dependent acceptance work
remains in progress.

Delegated-ledger checkpoint: 148 backend tests pass without skips in 108.66s;
11 frontend tests pass. Seven new integration tests cover source transaction rollback,
exact form metadata, revoked delegation, activation authority, retirement/duplicate
capture, immutable evidence, populated rollback refusal, loop/retry bounds and
broker-publish crash recovery. Ruff lint/format, Windows/Linux strict mypy (213
files), frontend lint/types/build and OpenAPI drift pass.
Hosted [37462108788](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37462108788)
passes both jobs on exact code commit `e1e84af7c04bd2a616c93d7e9ed256cd5b288ca2`,
including Linux tests/types, real browser identities, migrations and contract drift.
This verifies the ledger checkpoint; Phase 6 remains 0/8 accepted.

Action/consumer increment: 156 backend tests pass without skips in 115.18s,
including eight concurrent real Redis messages producing one committed effect.
New integration tests cover exact form/workflow pins, private source/target scope,
safe condition skipping, revocation, atomic multi-action rollback and bounded retry.
11 frontend tests pass. Ruff lint/format, Windows/Linux strict mypy (220 files),
frontend lint/types/build, Alembic/OpenAPI drift pass. Hosted action/worker run
[37465763364](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37465763364)
passes both jobs on `700db02b39dd94b8e7fdae2dff00ad8ddfcaee13`.
Final workflow-boundary refinement moves pinned-start persistence entirely into
the workflow application service; 24 affected tests and strict types pass locally.
Hosted refinement [37466610016](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37466610016)
passes both jobs on final code `4f8f6dab18e491ca10a80fdbedfa048c2d21dfb7`.
Phase 6 remains in progress with 0/8 accepted; no Phase 7 work.
No migration is added; existing development/test/browser head remains 8323b0dbac0e.

Private-storage reconciliation increment: 166 backend tests pass without skips in
113.16s, including ten new cleanup tests. 11 frontend tests pass. Ruff lint/format,
Windows/Linux strict mypy (223 files), frontend lint/types/build, Alembic/OpenAPI
drift and CLI help pass. Cleanup preserves referenced/recent/unknown objects,
rechecks authorization and references, serializes with in-flight uploads and uses
conditional deletion. Immutable committed intents survive delete/DB-commit crashes;
replay records missing objects without repeating effects. Actual S3-compatible
pagination and wrong/stale/matching ETag behavior pass. ADR-0012 records boundaries.
TD-005 is resolved. Hosted
[37480916988](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37480916988)
passes both jobs on exact code `adea461d687d2a07bf8a8bb8b335a15e9145c623`, including
Linux tests/types, browser/worker flows, migrations and contract drift. No migration
or retained-data rewrite. Phase 6 remains 0/8 accepted.

Periodic trigger increment: 178 backend tests pass without skips in 140.19s,
including twelve new timer/deadline tests and concurrent committed sessions.
11 frontend tests pass. Ruff lint/format, Windows/Linux strict mypy (229 files),
frontend lint/types/build/generated-contract drift, Alembic roundtrip/drift and
OpenAPI drift pass. Tests cover exact activation boundaries, 100-slot catch-up,
self-version matching, retirement/new-version progress, rollback, immutable marks,
private drafts, scoped revocation, 104-task pending pagination and duplicate effects.
Real committed concurrency verifies eight timer ticks and eight deadline ticks
emit two occurrences/two marks total, with locked-task revisit and task state preserved.
Migration a39df7b251c0 is applied to all three local databases; populated downgrade
refuses before evidence removal. Hosted
[37499621510](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37499621510)
passes both jobs on exact code `3beb19d610d67cbabb6cfb9e8025e1e99f762b06`, including
Linux tests/types, prior browser/worker flows, committed periodic concurrency,
source/evidence guards, migration roundtrip/drift and generated API contracts.
ADR-0013 and the runbook record the policy. Phase 6 remains 0/8 accepted.


In-app automation notice increment: 186 backend tests pass without skips in
154.05 seconds; 11 frontend tests pass. Eight new integration tests cover atomic
recipient privacy failure, transient retry rollback, task assignment/source links,
revoked source access, duplicate worker/read effects, immutable evidence, guarded
populated rollback and 120-notice chronological pagination. Typed inbox/detail/read
HTTP endpoints enforce tenant/workspace/recipient scope. The actual Keycloak PKCE
browser flow delivers one committed notice, reads it and retains read state after
refresh. Ruff lint/format (298 files), Windows strict mypy (236 source files),
frontend lint/types/build, empty migration roundtrip/drift, generated API drift and
OpenAPI drift pass. Migration 73eddd554d17 is applied to development, isolated test
and retained browser databases; no existing artifact is rewritten. ADR-0014 records
source-owned access and minimal notice policy. Hosted
[37504095044](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37504095044)
passes both backend/frontend jobs on exact code
`11b7818004d25754583d244d048992d41ca6c80b`, including Linux strict types,
real PKCE browser notice delivery/read, prior worker/periodic concurrency,
migration roundtrip/drift and generated contracts. Phase 6 remains in progress
with 0/8 accepted.

Automatic source notice increment: 195 backend tests pass without skips in 157.33s;
11 frontend tests pass. Nine new integration cases verify original/live eligibility,
notify-only access, cancellation, retry/dead letters, atomic rollback and immutable
evidence. Real Redis duplicate delivery and concurrent first-read tests each produce
one effect. Ruff lint/format (303 files), strict mypy (240 files), frontend
lint/types/build, empty migration roundtrip/drift, generated API/OpenAPI drift and
dispatcher CLI checks pass. ADR-0015 records the policy. Hosted
[37511023333](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37511023333)
passes both jobs on exact code `2cebf5ed8e4235e90056721c16932a45cc7e37de`, including
Linux tests/types, real PKCE browser and Redis worker flows, migrations and contracts.
Phase 6 remains 0/8 accepted.

Controlled replay increment: 203 backend tests pass without skips in 175.74s;
11 frontend tests pass. Eight new cases cover reviewed replay, scope/authority,
terminal states, preserved history, cancellation, stale progress and the attempt cap.
Eight committed concurrent requests produce one requeue/audit. A forced two-session
tenant/identity lock regression and the real browser/worker flows pass. Ruff
lint/format (308 files), strict mypy (243 files), frontend lint/types/build, migration
roundtrip/drift, generated API/OpenAPI drift and CLI checks pass. ADRs 0016/0017
record replay and locking policy. Hosted
[37514426474](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37514426474)
passes both jobs on exact code `ffac30f68a33964a1dbf45f2f14f65da30fe8d6e`, including
Linux tests/types, real browser/worker flows, committed replay and lock contention,
empty migration roundtrip/drift and generated contracts.
Phase 6 remains 0/8 accepted.

Historical handoff increment: all 215 backend tests pass without skips in 223.77s;
11 frontend tests pass. Twelve new cases cover exact original provenance, preview
purity, existing handoffs, reasons, operator/recipient revocation, minimal notify
access, 104-intent paging, rollback and committed duplicate apply/delivery. Eight
concurrent applies produce one capture/audit; eight deliveries one notice/attempt.
Ruff lint/format (314 files), strict mypy (248 files), frontend lint/types/build,
empty migration roundtrip/drift, generated API/OpenAPI drift and reconciliation CLI
checks pass. ADR-0018 records the policy. Hosted
[37519811189](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/37519811189)
passes both jobs on exact code `079b8c8afad24857f16617a6ed1339c40354f0e7`, including
Linux types/tests, real browser/worker flows, committed duplicate handoff/delivery,
empty migration roundtrip/drift and generated contracts.
Phase 6 remains 0/8 accepted.

Latest lifecycle validation: 227 backend tests pass without skips in 399.71s;
14 frontend tests pass. Ruff lint/format (318 files), strict mypy (251 files),
frontend lint/types/build, empty migration roundtrip/drift and OpenAPI/generated
client drift pass. Real browser PKCE preserves the link and accepts exactly once;
committed concurrency produces one invitation/grant/audit across eight retries.
Hosted [38036138271](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38036138271)
passes both jobs on exact final code `82cf4e5ff8b17088bef9784681d270ef3eceba07`,
including Linux tests/types, browser PKCE, committed concurrency, migrations and
generated contracts. The deterministic fixture repair also passes 46 affected tests
locally in 101.42s. Phase 6 remains 0/8 accepted.

Latest explicit email capture validation: all 250 backend tests pass without skips
in 223.08s, including real browser opt-in, concurrent invitation retries and a full
email-only rule/Redis/loopback SMTP pipeline producing one message/attempt from
eight duplicate messages. All 14 frontend tests pass. Ruff check/format (334 files),
strict mypy (265 files), frontend lint/types/build, migration round-trip/drift and
generated OpenAPI/client checks pass. Hosted
[38044650329](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38044650329)
passes both jobs on exact code `6fd5082ea167d0b6ad97836afe3a075ad055dd14`.
Phase 6 remains 0/8 accepted; no external mail was sent.

## Automation administration validation

All local gates pass: 261 backend tests without skips in 242.55s, 16 frontend
tests, Ruff check/format (338 files), strict mypy (268 files), frontend lint/types/
build, migration round-trip/drift and generated OpenAPI/client checks. Real PKCE
browser author/save/activate/replay/clone/retire and eight committed concurrent
replays producing one requeue/audit pass. Ten new API/integration tests cover
scope isolation, manager/elevated authority, immutable versions, exact 104-row
rule/version/run pages, reasons/stale reviews, attempt cap, archived inspection
and revoked original delegation. No migration or retained-data rewrite. Hosted [38047837127](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38047837127)
passes backend and frontend jobs on exact code
`fe4ebc867b2cd01d62a394db048e696125e7844c`, including Linux strict types,
real PKCE administration/replay, committed concurrent applies, migrations and
generated contracts. Phase 6 remains 0/8 accepted; no Phase 7 work.

## Email recovery console validation

All local gates pass: 272 backend tests without skips in 261.34s and 18 frontend
tests. Ruff check/format (342 files), strict mypy (271 files), frontend lint/types/
build, migration round-trip/drift and generated OpenAPI/client checks pass. Eleven
new API/integration cases cover scope/privacy, exact filtered 104-row chronology
with timestamp ties, invalid/foreign cursors, preserved evidence after source expiry
and revoked delegation, replay reason/hash/uncertain acknowledgement, terminal
states, lifetime cap and populated index rollback. Real PKCE browser recovery and
eight committed concurrent reviews produce one requeue, then one provider effect.
No external email is sent; fake/loopback tests only. Hosted [38049979000](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38049979000)
passes backend/frontend jobs on exact code
`b0b9d052c6d0f78278346500e146fc97b05ec8b5`, including Linux strict types,
real PKCE email recovery, committed concurrent replay/worker delivery, migrations
and generated contracts. Phase 6 remains 0/8 accepted; no Phase 7 work.

## Generic task validation

Latest generic-task validation: all 285 backend tests pass without skips in
259.33s, including real PKCE browser claim/completion and committed concurrent
Redis delivery, claims and completion retries. All 18 frontend tests pass.
Ruff lint/format (345 files), strict mypy (273 files), frontend lint/types/build,
OpenAPI/generated client checks and migration roundtrip/drift pass. Thirteen new
integration cases cover scope/authority, immutable snapshots/evidence, atomic
failure recovery and preserved form/guarded generic rollback. Hosted
[38052949486](https://github.com/AminMShahnani/industrial-operations-project-data-platform/actions/runs/38052949486)
passes backend/frontend jobs on exact code
`d25ad7a5e672b2e5d3240b36db8964623a6c7d1d`, including Linux strict types,
real PKCE execution, committed Redis/claim/completion concurrency, migrations and
generated contracts. Phase 6 remains 0/8 accepted.

## Controlled annotation validation

All 298 backend tests pass without skips in 274.79s; all 18 frontend tests pass.
Ruff lint/format (348 files), strict mypy (275 files), frontend lint/types/build,
Alembic roundtrip/drift and generated OpenAPI/client checks pass. Thirteen new
integration cases verify scope/fresh authority, immutable audit binding, exact
kind/case and cursor rules, terminal/cap handling, atomic retry and guarded rollback.
Real PKCE browser refresh/filter/late-response handling and committed Redis/
eight concurrent appends pass. Exact-code hosted verification is pending.
Phase 6 remains 0/8 accepted.

## Migration status

Development, isolated test and retained browser databases are at e49b7d83af20.
Project annotations add composite scope/author/audit bindings, immutable history
guards and a cursor index without rewriting retained projects or audits. Empty
annotation rollback preserves existing audits; populated rollback locks writes
and refuses before DDL. See ADR-0025 and the Phase 6 runbook.
Generic task migration preserves form pins/history and adds kind/origin/completion
constraints and guards. Form-only roundtrip and drift pass; populated generic
rollback locks writes and refuses before DDL. No retained history is deleted.
Generic-task hosted verification passes on d25ad7a / run 38052949486; previous email console proof
below remains the accepted baseline for that increment.
Email console lookup indexes add chronological organization/state cursor access.
Populated index downgrade preserves all delivery/attempt/audit evidence; no data
rewrite is performed. All local/hosted gates pass on exact code b0b9d05 / run 38049979000.
Prior explicit email channel migration 5caef6ad5721 remains intact.
Explicit email channels add immutable notice visibility and a filtered cursor index.
Existing notice IDs/source/audit/read history remain intact. Empty/default-only
round-trip and drift pass; email channel evidence blocks populated rollback.
Prior SMTP migration 208f826ca492 preserves immutable source/attempt history and
refuses populated rollback. See the Phase 6 runbook for source/worker rollback.
Verified-email invitation migration preserves old mode/digest/timestamps, enforces
credential-mode coherence and immutable binding/one-way acceptance. Token-only
rollback preserves rows; populated new-mode rollback refuses before data changes.
Historical handoff migration adds reversible lookup indexes
only; populated rollback preserves all evidence. Existing notice/source IDs and
audit/read history are retained.
Automatic delivery adds immutable attempts and notice origin/intent metadata.
Existing notice identities, source/run bindings and read/audit history are retained.
Immutable notice/read evidence adds composite tenant keys and exact source/action
binding; populated rollback refuses before dropping retained history.
Periodic generation adds immutable timer/task-deadline evidence with exact
source/slot binding and guarded populated rollback. No retained artifact is rewritten.
Phase 6 adds seven guarded outbox/rule/run/attempt/receipt tables. Empty roundtrip
and Alembic drift pass; populated downgrade refuses before evidence deletion.
Rollback strategy: docs/operations/PHASE_6_RUNBOOK.md. Phase 5 adds
scoped definitions/versions, instances, visits/recipient snapshots, immutable
actions/notification intents/revisions, proven task transitions and review roles.
Empty migration roundtrip/drift and populated evidence rollback refusal are tested.
Final local/hosted migration gates pass. Phase 4 adds
guarded immutable schedules, tasks, recipients, shifts, triggers, reminders and
project milestones. Empty roundtrip/drift pass; populated downgrade refuses.
Phase 3 adds
464245e2e729 and dbd58764eb86, with immutable versions/submissions/files,
composite ownership protection and populated rollback guards. Phase 2 adds
99e791752349 then 4c982bc7d8c5. Composite tenant/workspace keys, department-only
relationships, immutable definitions/identities and history protection are tested.
Populated downgrade refuses before deletion; documented restore/reconciliation
strategies are in docs/operations/PHASE_2_RUNBOOK.md, PHASE_3_RUNBOOK.md and PHASE_4_RUNBOOK.md.
No legacy migration performed.

## Known tech debt
TD-001 through TD-004 remain assigned to their owning/deployment phases. TD-005
reconciliation is resolved; retention/quota/backup verification remains Phase 10.
Large background transfers belong to Phase 7. See TECH_DEBT.md.
