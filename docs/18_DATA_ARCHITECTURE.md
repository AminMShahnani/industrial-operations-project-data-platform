# Data Architecture

## PostgreSQL rationale
The production domain has strong relationships, scoped memberships, approvals, versioning, transactions and reporting. PostgreSQL provides relational integrity plus JSONB flexibility for form schemas/submission payloads.

## Hybrid relational + JSONB
Relational tables store identity, scope, lifecycle and references. JSONB stores controlled dynamic definition/data snapshots.

## Key tables (conceptual)
organizations
users, organization_memberships
workspaces, workspace_memberships
departments, department_memberships
projects, project_memberships, department_project_grants
roles, permissions, grants
forms, form_versions, form_assignments
schedules, schedule_versions, task_occurrences
submissions, submission_revisions
workflow_definitions, workflow_versions, workflow_instances, workflow_actions
automation_rules, automation_versions, automation_runs
master_data_types, master_data_records
files
notifications
audit_events
domain_packs, domain_pack_versions, pack_installations, pack_artifact_provenance
outbox_events

## IDs
Use UUIDv7 or another time-sortable globally unique identifier after ADR confirmation.

## Deletion
Use explicit lifecycle states/soft deletion where historical reference matters. Do not cascade-delete operational history.

## Indexing
All high-volume query paths must include organization/scope and status/date indexes. JSONB indexes only for proven query patterns.
