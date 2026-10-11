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

This is a personal operational queue, not a workspace-wide overdue KPI. Members with
current `schedule.manage` at the selected scope can request the same endpoint with
`scope=aggregate`. Aggregate queries delegate to the Tasks service's project mode,
which rechecks that permission at the workspace/project scope. The response still
omits recipient, claimant and submission identity. Personal scope remains the
default; personal readers receive 403 if they request aggregate scope.

Both scopes are read-only and do not materialize cached values; each request uses
current task state and authorization. Saved report definitions are creator-private
under ADR-0029 and must recheck dataset permissions at execution. Sharing is not
enabled.

## Master-data import mapping

CSV/XLSX imports remain create-only and bounded to the existing 1,000-row/4 MiB
limits. Canonical headers can preview directly; other headers return an explicit
mapping step. Each source header maps to at most one declared built-in or dynamic
field, and each field can be selected once. `code` and `name` are required; unused
columns may be ignored. Review the mapped rows and issues before apply. Apply is
bound to the exact file SHA-256, mapping SHA-256 and type version. If any changes,
preview again. Source IDs do not overwrite or become record IDs. All resulting
records pass normal Master Data validation and immutable audit capture.

## Saved report definitions (initial slice)

`POST /api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved`
creates a private definition over the governed `overdue_tasks` dataset. The bounded
contract supports the declared columns and filters only; it does not accept SQL or
arbitrary joins. The owner can list, read, create and edit through the browser, update
with an expected version, run, and archive their definition. Each create/update appends an immutable version with a
canonical SHA-256 definition digest and an exact audit event. Archive is an audited
state transition; it does not erase version history. Every run resolves current task
state and rechecks personal `task.read` or aggregate `schedule.manage` at its stored
scope. Sort order currently supports task ID ascending or descending, with the task
query applying the matching cursor predicate. Grouping by task state returns filtered
counts from an unpaged, bounded-cardinality SQL aggregate in the Tasks module under
ADR-0031; grouped output contains no task identities or row data. Other users receive
no definition through listing or direct lookup. Sorting by other columns and grouping
by other dimensions/measures are not yet available.

Migration `41a9c1d7e5b0` adds tenant/workspace/owner-bound identities, immutable
definition versions, and mutable audited archive state. It refuses populated
rollback to preserve report and audit history; take a verified backup and retain the
revision when reports exist. The empty-schema rollback path drops state, version and
identity tables and their immutability guards. The Phase 6 audit-key round-trip test
must unwind this revision before removing tenant-linked audit constraints.

## Creator-private dashboards (initial widget slice)

Dashboards use `GET/POST /reports/dashboards` and
`GET/PUT /reports/dashboards/{dashboard_id}`. A dashboard definition is bounded to
six `table`, `overdue_list`, `status_distribution`, `bar` or `metric` widgets, each
referencing one saved report belonging to the same creator and workspace.
Status-distribution, bar and metric widgets require a report grouped by state. The
bar widget renders its finite state/count buckets with accessible meter controls. A metric
shows the sum of overdue state counts. `GET /reports/dashboards/{dashboard_id}/run`
executes each referenced report through the reporting service, rechecking current
dataset permissions and returning at most 100 rows per widget. Dashboard owners can
archive their layout; other workspace members receive no definition or result.

Migration `8d77c0f21a46` adds immutable, audited dashboard versions and guarded
archive state. Empty rollback/reapply and populated rollback refusal are covered by
PostgreSQL tests. The populated rollback guard retains definitions and audits; use a
verified backup and retain the revision when dashboard history exists. Dashboard
widgets include status distribution, a bar chart and total overdue count, derived
from filtered state counts. Trend/line widgets require a saved report grouped by
due-date week under ADR-0033. The Tasks query returns the current overdue backlog
in the current UTC week plus the prior 11 weeks, including empty week buckets and
one older bucket. These counts are current-state snapshots by due-date cohort, not
historical state transitions. Durable export jobs remain Phase 7 work.

## Saved-report exports and durable jobs

`GET /reports/saved/{report_id}/export?format=csv|xlsx|pdf` reruns the owner's saved
definition with current dataset authorization and returns one ID-ordered page of at
most 100 rows (or finite state groups). Responses are attachments with
`private, no-store` caching. CSV formula-leading text is escaped; XLSX cells are
written as strings, never formulas. PDF is generated as bounded text-only pages.
Exports contain only selected columns (or `state,count` for grouped reports). A
report with another page returns `export_requires_background_job` to the browser,
which queues a durable export instead.

`POST /reports/saved/{report_id}/export-jobs` accepts `csv`, `xlsx` or `pdf` and
returns a creator-private job bound to the immutable report version, digest, scope,
format and workspace/project. `GET /reports/export-jobs` and
`GET /reports/export-jobs/{job_id}` expose only the creator's job status. The
Dramatiq worker polls the durable table, safely tolerates duplicate ID-only queue
messages, recovers `running` leases after five minutes, bounds reports at 10,000
rows and artifacts at 50 MiB, and stores output under the private organization
prefix. Retries overwrite the same key and verify the definition digest. Job queue,
completion, revocation and expiry transitions are audited.

`GET /reports/export-jobs/{job_id}/download` rechecks creator ownership and current
dataset permission, then reads the private object and checks its recorded size and
SHA-256 before returning bytes. No persistent or signed storage URL is exposed.
Completed artifacts expire after the accepted 24-hour retention period in ADR-0034;
the worker removes them idempotently and records expiry.

## Rollback

Migrations `92e3b0c4a7d1` and `a16c3e902bf4` add the durable job ledger and bounded
recovery index. The index can be removed while retaining the job table. The job-table
downgrade locks the table and refuses when any job history remains, preserving audit
references and object-retention metadata; restore a verified database and object
storage backup before a coordinated rollback. Drain the dispatcher/worker first.
Task persistence and the existing task inbox remain unchanged.
