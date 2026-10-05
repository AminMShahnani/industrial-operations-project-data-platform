# Workspace and Project Model

## Workspace
A long-lived organizational collaboration boundary. Contains departments, teams, projects, shared templates, shared master data, dashboards and configuration.

## Department
Represents organizational grouping. Department membership does not automatically imply all project access unless policy says so.

## Project
Operational boundary with lifecycle, members, department grants, domain entities, forms, tasks and reports.

## Department-project access
Many-to-many entity `DepartmentProjectGrant`:
- department_id
- project_id
- permission_profile/role
- effective_from/to
- optional constraints

## Direct user access
ProjectMembership supports users who need access independent of department membership.

## Project lifecycle
Lifecycle is configurable from a controlled state-machine definition. Default example: planned -> active -> suspended -> closing -> closed -> archived.

## Historical integrity
Removing a user's active access must not erase historical authorship, approvals or audit records.
