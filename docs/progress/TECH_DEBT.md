# Technical Debt Register

Empty at project start. Every intentional compromise must include owner/context, impact, target phase and remediation plan.

| ID | Owner/context | Impact | Target/remediation |
| --- | --- | --- | --- |
| TD-001 | Operations; foundation telemetry | HTTP metrics/traces exist; collectors, alerts and infrastructure metrics are not deployed | Owning feature phases and Phase 10: deploy collectors, add DB/queue/storage/job telemetry and alerts |
| TD-002 | Frontend/operations; foundation SPA | Production CSP, ingress and static deployment not yet configured | Phase 10: production headers, private operations endpoints and accessibility/E2E verification |
| TD-003 | Migration team; legacy source/data absent | Cannot inspect actual Mongo schema or validate live migration counts | Phase 10: obtain immutable legacy fixtures/export inventory; mapping/checksum and parallel-read tests; no cutover until verified |
| TD-004 | Identity/operations; external provider deployment | Local PKCE fixture is verified; production provider, restricted runtime DB role and ingress topology are not deployed | Phase 10 deployment gate: provision provider and runtime/migration roles, validate rate limits and end-to-end production trust |

Phase 1 introduces audited tenant persistence without an authentication bypass or
industry coupling. Later phase namespaces remain planned ownership rather than
completed implementations. Provider-level logout and automated invitation delivery
remain documented provider responsibilities and Phase 6 work respectively.

Phase 2 preparation adds no implementation compromise. Q-003 is a pending
security ownership decision, tracked in OPEN_QUESTIONS.md rather than tech debt.
