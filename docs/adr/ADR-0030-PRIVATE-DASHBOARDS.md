# ADR-0030: Creator-private dashboards

- Status: Accepted
- Date: 2026-10-11
- Decision owner: Project owner

## Context

Phase 7 dashboard definitions reference governed datasets and can reveal the
creator's saved filters or cross-user operational information. The reporting docs
do not define a dashboard audience. ADR-0029 explicitly leaves dashboard sharing
for a separate authorization decision.

## Decision

Phase 7 dashboards are private to their creator within their organization and
workspace/project scope. Only the creator can list, read, update, execute or archive
a dashboard. Each widget references a saved report owned by that same creator.
Every dashboard execution rechecks the saved report's current dataset authorization.
The owner selected creator-private dashboards on 2026-10-11.

## Consequences

- Dashboard identity and immutable definition versions retain tenant, scope and owner.
- UUID knowledge does not grant dashboard or saved-report access.
- `schedule.manage` remains required for aggregate overdue-task widgets per ADR-0028.
- Sharing and team dashboards require a later explicit authorization decision.
- Widgets use bounded saved-report references; arbitrary SQL and joins remain unavailable.
