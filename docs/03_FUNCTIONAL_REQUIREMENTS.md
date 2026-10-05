# Functional Requirements

## Organization administration
FR-001 create/suspend organizations.
FR-002 configure organization settings, branding, locale, timezone, units.
FR-003 manage organization admins.
FR-004 configure enabled Domain Packs and integrations.

## Workspace/project administration
FR-010 create workspaces.
FR-011 assign one or more workspace managers.
FR-012 create departments/teams.
FR-013 create projects within workspaces.
FR-014 map departments to projects with scoped permissions.
FR-015 assign users directly to one or more projects.
FR-016 configure project lifecycle, dates, metadata, locations, assets and optional domain entities.

## Forms
FR-020 create forms from scratch or templates.
FR-021 compose sections, fields, tables, repeating groups.
FR-022 define validation, conditional visibility, formulas, lookups and defaults.
FR-023 version forms; published versions are immutable.
FR-024 activate/deprecate form versions.
FR-025 bind forms to workspace/project/domain scope.
FR-026 import form definitions from supported pack/template format.

## Scheduling/tasks
FR-030 schedule forms using one-time, interval, calendar and RRULE schedules.
FR-031 assign to users, roles, departments, teams or shifts.
FR-032 materialize task occurrences idempotently.
FR-033 support due/overdue/upcoming states and reminders.
FR-034 expose personal/team task inboxes.

## Submission/workflow
FR-040 save drafts and autosave.
FR-041 validate against exact form version.
FR-042 submit a form and preserve immutable submitted snapshot.
FR-043 route through configurable workflow.
FR-044 review, reject, return, approve and close.
FR-045 attach files/comments where allowed.
FR-046 record signer identity, action, time and reason.

## Automation
FR-050 support event + condition + action rules.
FR-051 actions may create tasks, notify, update allowed metadata, trigger workflows, call webhooks, or launch derived forms.
FR-052 automation runs must be logged, retryable and idempotent.

## Reporting/export
FR-060 filtered datasets and saved reports.
FR-061 standard dashboards per project/workspace.
FR-062 XLSX/CSV/PDF export.
FR-063 organization-owned export templates.

## Domain Packs
FR-070 install a pack at organization/workspace/project scope where allowed.
FR-071 preview changes before installation.
FR-072 version/upgrade packs with migration checks.
FR-073 prevent deletion if dependent live data would become invalid.
FR-074 allow organization overlays without editing vendor pack source.
