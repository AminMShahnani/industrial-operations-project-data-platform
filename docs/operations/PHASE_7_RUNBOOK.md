# Phase 7 reporting, export and import runbook

## Personal overdue-task dataset (initial slice)

Authenticated members can request:

`GET /api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/overdue-tasks`

Optional query parameters are `project_id` and the opaque `cursor` returned by the
prior page. Responses contain at most 100 rows and expose only task ID, optional
project ID, kind, name, state and due timestamp. The dataset delegates to the task
module's existing personal inbox query, preserving active membership, `task.read`,
tenant/workspace/project scope, current caller assignment and live overdue state
rules. It does not show other recipients' tasks or claimant/submission identifiers.
Follow `next_cursor` with the same organization, workspace and project filter.

This is a personal operational queue, not a workspace-wide overdue KPI. Aggregate
datasets require a separately reviewed reporting permission/query contract before
they can expose task activity across users. This endpoint is read-only, creates no
migration or audit write, and does not materialize cached values; each request uses
current task state and current authorization.

## Rollback

No schema migration or background job is introduced by this slice. Application
rollback consists of removing the reporting route/service and generated contract
entry; task persistence and existing task inbox behavior remain unchanged.
