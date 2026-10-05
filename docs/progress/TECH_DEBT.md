# Technical Debt Register

Empty at project start. Every intentional compromise must include owner/context, impact, target phase and remediation plan.

| ID | Owner/context | Impact | Target/remediation |
| --- | --- | --- | --- |
| TD-001 | Operations; foundation telemetry | HTTP metrics/traces exist; collectors, alerts and infrastructure metrics are not deployed | Owning feature phases and Phase 10: deploy collectors, add DB/queue/storage/job telemetry and alerts |
| TD-002 | Frontend/operations; foundation SPA | Production CSP, ingress and static deployment not yet configured | Phase 10: production headers, private operations endpoints and accessibility/E2E verification |
| TD-003 | Migration team; legacy source/data absent | Cannot inspect actual Mongo schema or validate live migration counts | Phase 10: obtain immutable legacy fixtures/export inventory; mapping/checksum and parallel-read tests; no cutover until verified |

No business persistence, auth bypass, industry coupling or known critical security
defect is introduced by Phase 0. Empty module namespaces are planned ownership,
not completed module implementations.
