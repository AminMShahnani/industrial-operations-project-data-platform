# Technical Debt Register

Empty at project start. Every intentional compromise must include owner/context, impact, target phase and remediation plan.

| ID | Owner/context | Impact | Target/remediation |
| --- | --- | --- | --- |
| TD-001 | Operations; foundation telemetry | HTTP metrics/traces exist; collectors, alerts and infrastructure metrics are not deployed | Owning feature phases and Phase 10: deploy collectors, add DB/queue/storage/job telemetry and alerts |
| TD-002 | Frontend/operations; foundation SPA | Production CSP, ingress and static deployment not yet configured | Phase 10: production headers, private operations endpoints and accessibility/E2E verification |
| TD-003 | Migration team; legacy source/data absent | Cannot inspect actual Mongo schema or validate live migration counts | Phase 10: obtain immutable legacy fixtures/export inventory; mapping/checksum and parallel-read tests; no cutover until verified |
| TD-004 | Identity/operations; external provider deployment | Local PKCE fixture is verified; production provider, restricted runtime DB role and ingress topology are not deployed | Phase 10 deployment gate: provision provider and runtime/migration roles, validate rate limits and end-to-end production trust |

| TD-005 | Files/operations; DB and object storage have separate transactions | Immediate rollback compensation is tested; if cleanup fails, an inaccessible private orphan may remain | Phase 6: idempotent inventory/reconciliation with grace period and audited cleanup; Phase 10: retention/quota/backup verification |

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
