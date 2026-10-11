# Implementation backlog

Phases are sequential. No later phase starts until the current checklist passes.

| Phase | Deliverables | Gate |
| --- | --- | --- |
| 0 | Reproducible backend/frontend tooling, module boundaries, CI, infrastructure, reversible baseline migration, health and logging | PHASE_LOG Phase 0 checklist |
| 1 | Identity, organizations, workspaces, invitations, scoped IAM, audited grants | Authentication decision resolved; tenant isolation and privilege escalation tests |
| 2 | Projects, departments, grants, governed master data | Relational invariants, history preservation, import dry runs |
| 3 | Immutable form versions, safe expressions, validation, submissions, attachments | Cycle/immutability tests, tenant-safe runtime, upload security |
| 4 | Schedule versions, deterministic occurrences, inbox, reminders | Accepted: P4-01 through P4-08; Q-004 resolved; hosted run 37432881526 |
| 5 | Workflow versions, approval policies, reject/resubmit, amendments | Immutable action/audit history and authorization tests |
| 6 | Automation, durable outbox processing, notifications | ACCEPTED 8/8; backend/frontend hosted run 38079026238 on b97822e; deployment secret mount and egress verified per owner |
| 7 | Governed datasets, dashboards, CSV/XLSX/PDF, import wizard | P7-01 through P7-08 defined in PHASE_LOG; generation/download authorization, bounded reads |
| 8 | Pack contracts, dependency resolution, install/upgrade/uninstall, SDK | Compatibility, provenance, overlay and rollback tests |
| 9 | Oil & Gas pack forms, registries, workflows, KPIs, mappings | Local implementation and verification complete; exact-code hosted CI remains for P9-08; see Phase 9 final gate in PHASE_LOG |
| 10 | Security, performance, restore, legacy migration validation, UAT | Full Definition of Done and operational evidence |

Each phase must add detailed acceptance criteria before implementation, identify
source requirements, add migration rollback instructions, and record gate evidence.
