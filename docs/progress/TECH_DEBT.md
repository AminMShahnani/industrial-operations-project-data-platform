# Technical Debt Register

Phase 6 invitation lifecycle (2026-10-10): Q-007 is resolved and ADR-0019 accepts
token-free verified-email invitations while preserving bearer-token history.
Creation/acceptance API and browser flow are implemented with guarded migration.
SMTP dispatch, immutable attempts, uncertain outcomes and controlled replay remain
current Phase 6 work, not deferred debt. No phase acceptance is introduced.

Empty at project start. Every intentional compromise must include owner/context, impact, target phase and remediation plan.

| ID | Owner/context | Impact | Target/remediation |
| --- | --- | --- | --- |
| TD-001 | Operations; foundation telemetry | HTTP metrics/traces exist; collectors, alerts and infrastructure metrics are not deployed | Owning feature phases and Phase 10: deploy collectors, add DB/queue/storage/job telemetry and alerts |
| TD-002 | Frontend/operations; foundation SPA | Production CSP, ingress and static deployment not yet configured | Phase 10: production headers, private operations endpoints and accessibility/E2E verification |
| TD-003 | Migration team; legacy source/data absent | Cannot inspect actual Mongo schema or validate live migration counts | Phase 10: obtain immutable legacy fixtures/export inventory; mapping/checksum and parallel-read tests; no cutover until verified |
| TD-004 | Identity/operations; external provider deployment | Local PKCE fixture is verified; production provider, restricted runtime DB role and ingress topology are not deployed | Phase 10 deployment gate: provision provider and runtime/migration roles, validate rate limits and end-to-end production trust |

| TD-005 (resolved) | Files/operations; DB and object storage have separate transactions | Reconciliation verified locally and hosted on adea461 / run 37480916988 | Phase 6: bounded inventory, explicit grace, fresh references/authority, upload locks, conditional deletion and audited replay implemented (ADR-0012); Phase 10 retains retention/quota/backup verification |

Phase 1 introduces audited tenant persistence without an authentication bypass or
industry coupling. Later phase namespaces remain planned ownership rather than
completed implementations. Provider-level logout and automated invitation delivery
remain documented provider responsibilities and Phase 6 work respectively.

Phase 2 resolves Q-003 in ADR-0007. Transfers are deliberately bounded to
1000 rows per synchronous import and 100 records per export page. Large background
transfers belong to Phase 7; queue idempotency and load acceptance remain required
in their owning phases. No legacy data was deleted or migrated.

Phase 3 supplies trusted default-context ports. Scheduling/workflow providers are
owning-phase dependencies, without inferring an approved state. Scanner provisioning
and patched engine/signature maintenance are deployment responsibilities. Missing
scanners always deny uploads.

Phase 4 preparation (2026-10-06): no new implementation debt introduced. Existing
Phase 6 worker/notification and Phase 10 deployment responsibilities remain assigned
to their owning phases. Phase 4 must provide reproducible periodic materialization,
idempotent in-app reminders and typed handoffs; later delivery adapters do not waive
its scheduling/task acceptance criteria. Q-004 is an open requirement, not tech debt.

Q-004 was subsequently resolved by the user: one shared task/atomic claimant.
Phase 4 uses a bounded documented recurrence profile, 1000 recipients per assignment,
2000 work items per generation window and bounded activation supersession. Large
replacement plans and throughput/load verification remain explicit operational
planning and Phase 10 validation; these bounds are not silently expanded. No queue
framework introduced before Phase 6 selection. Current in-app reminder records are
the durable typed handoff for that phase's notification delivery.

Phase 4 accepted on d92a10f / hosted run 37432881526. No deferred Phase 4 acceptance
criterion. TD-001 through TD-005 and the explicitly documented future-phase
deployment/delivery responsibilities remain assigned to their owners.

Phase 5 preparation (2026-10-06): no implementation debt introduced. Q-005 is a
pending security requirement, not deferred work. Phase 5 acceptance is 0/8;
Phase 6 worker delivery and Phase 10 deployment obligations retain their owners.

Phase 5 definition foundation: migration e049d194ba38 preserves prior forms,
submissions, attachments and tasks. Missing runtime/UI integration remains current
Phase 5 work; it is not reclassified as technical debt or deferred acceptance.
Q-005 resolved; no new industry dependency or execution framework introduced.

Phase 5 runtime verification: API/UI/runtime integration is implemented and under
acceptance testing. Remaining assignment/browser/concurrency/gate verification is
current Phase 5 work, not deferred debt. Typed notification intents hand off to
Phase 6; existing TD-001 through TD-005 retain their owners.

Phase 5 accepted on d91dfce / hosted run 37454353238 with no deferred acceptance
criterion or new implementation debt. Documented bounds and unsupported manager
context are explicit product profiles; delivery/deployment obligations retain their
Phase 6/10 owners. Phase 6 has not started.

Phase 6 preparation: TD-005 reconciliation and notification/invitation delivery
remain current-phase requirements. Q-006 is a security decision, not deferred debt.
Worker/outbox foundation alone will not satisfy Phase 6 acceptance.

Phase 6 foundation: scoped event contracts and transport have tests, but durable
outbox/runs, actions, notification delivery/UI and reconciliation remain current
implementation work. No retained data or migration was changed; no new bypass.

Phase 6 delegated ledger checkpoint: Q-006 resolved in accepted ADR-0011. Guarded
outbox/rule/run persistence and source capture are implemented and tested. Action
handlers, worker consumers, notifications/email/invitations, scoped UI and TD-005
reconciliation remain Phase 6 implementation requirements, not deferred debt.
No production worker rollout or new authority bypass is introduced.

Ledger checkpoint e1e84af passes hosted run 37462108788 and all local checks.
No remaining Phase 6 requirement is deferred or converted into technical debt.

Action/consumer increment: four authorized action families and the real worker are
implemented and tested. Generic tasks, tags/flags, notification/webhook adapters,
timer/due events, email/invitations, API/UI, telemetry and TD-005 reconciliation remain
required Phase 6 work. No production rollout or acceptance is claimed for partial
adapters. The existing migration and operational-history safeguards remain in force.

Action/worker code 700db02 passes hosted run 37465763364. Pinned-start persistence
is owned by the workflow application service; no direct cross-module persistence
access is introduced. Phase 6 remains in progress without deferred acceptance.

Final action/worker refinement 4f8f6da passes hosted run 37466610016. No new debt
or deferred phase requirement is introduced by this increment.

Private-storage reconciliation implements TD-005 with ten new tests and all local
checks passing (166 backend/11 frontend). ADR-0012 and the Phase 6 runbook document
grace, committed intents, upload/reference race protection, conditional deletes and
crash-safe replay. Hosted run 37480916988 passes both jobs on exact code adea461;
TD-005 reconciliation is resolved. Attachment
retention, quota and backup policies retain their Phase 10 owners. Remaining Phase 6
requirements are not converted into debt or deferred to Phase 7.

Periodic triggers are implemented in their owning Phase 6 with ADR-0013, guarded
evidence migration, bounded restart/catch-up and twelve new tests. All local checks
pass (178 backend/11 frontend); hosted run 37499621510 passes both jobs on exact
code 3beb19d. No new debt or
acceptance deferral is introduced. Notifications/actions/API/UI/telemetry remain
current-phase implementation requirements; TD-005 stays resolved.


In-app automation notices and their typed personal inbox API/UI are implemented
with eight new integration tests, real PKCE browser delivery/read verification and
all local gates passing (186 backend/11 frontend). ADR-0014 documents boundaries.
Automatic task/workflow consumers, email/invitations, remaining handlers, rule/run
management UI and telemetry stay in Phase 6; no new debt or acceptance deferral.
Hosted run 37504095044 passes both jobs on exact code 11b7818; no new debt.


Automatic in-app consumer/worker routing and durable retry/skip evidence are
implemented within Phase 6. ADR-0015 documents source-owned authorization and
additive migration. Historical handoff reconciliation, controlled notification
replay, email/invitations, remaining handlers/UI and telemetry remain current-phase
requirements. No new debt, data rewrite or acceptance deferral is introduced.
All local gates pass (195 backend/11 frontend tests), including real worker duplicate
delivery and concurrent first reads. Hosted run 37511023333 passes both jobs on
exact code 2cebf5e, including Linux gates, browser/worker flows and migrations.

Controlled notification replay is implemented with preview/apply, immutable audit,
fresh operator authority and unchanged source/audience/attempt history (ADR-0016).
Eight new test cases include committed eight-way concurrent apply. All local gates
pass (203 backend/11 frontend), including forced lock-order contention and real
browser/worker flows. Hosted run 37514426474 passes both jobs on exact code ffac30f,
including Linux gates, committed concurrency and migrations. No new debt or acceptance
deferral; historical handoff
reconciliation, management API/UI and other remaining requirements stay in Phase 6.
The reproducible user/organization lock-order deadlock is repaired through the
organization-owned lock contract (ADR-0017), retaining existing tenant serialization.
Measuring and optimizing tenant-level contention belongs to Phase 10 performance
verification; no concurrency safeguard is weakened for this increment.

Historical notify/reminder handoff reconciliation is implemented as a bounded
reviewed operator command (ADR-0018), with original source snapshots, current audit,
notification-only delivery and existing-handoff preservation. Index migration is
reversible with populated history. All local gates pass (215 backend/11 frontend),
including retained provenance, populated rollback and committed duplicate effects.
Hosted run 37519811189 passes both jobs on exact code 079b8c8, including Linux
gates, real browser/worker flows, committed duplicate handoffs and migrations. No new
debt or acceptance deferral; email/invitations, management API/UI, other action
handlers and telemetry remain current Phase 6 work.
