# Implementation backlog

Phases are sequential. No later phase starts until the current checklist passes.

| Phase | Deliverables | Gate |
| --- | --- | --- |
| 0 | Reproducible backend/frontend tooling, module boundaries, CI, infrastructure, reversible baseline migration, health and logging | PHASE_LOG Phase 0 checklist |
| 1 | Identity, organizations, workspaces, invitations, scoped IAM, audited grants | Authentication decision resolved; tenant isolation and privilege escalation tests |
| 2 | Projects, departments, grants, governed master data | Relational invariants, history preservation, import dry runs |
| 3 | Immutable form versions, safe expressions, validation, submissions, attachments | Cycle/immutability tests, tenant-safe runtime, upload security |
| 4 | Schedule versions, deterministic occurrences, inbox, reminders | PHASE_LOG P4-01 through P4-08; Q-004 pending before assignment implementation |
| 5 | Workflow versions, approval policies, reject/resubmit, amendments | Immutable action/audit history and authorization tests |
| 6 | Automation, durable outbox processing, notifications | Safe actions, retries, dead letters and idempotency |
| 7 | Governed datasets, dashboards, CSV/XLSX/PDF, import wizard | Generation/download authorization, bounded reads |
| 8 | Pack contracts, dependency resolution, install/upgrade/uninstall, SDK | Compatibility, provenance, overlay and rollback tests |
| 9 | Oil & Gas pack forms, registries, workflows, KPIs, mappings | Pack contract tests; no industry logic in Core |
| 10 | Security, performance, restore, legacy migration validation, UAT | Full Definition of Done and operational evidence |

Each phase must add detailed acceptance criteria before implementation, identify
source requirements, add migration rollback instructions, and record gate evidence.
