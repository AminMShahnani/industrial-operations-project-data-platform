# IAM and Authorization

## Model
Use RBAC for understandable role bundles plus scoped grants and contextual policy checks.

## Default roles
PlatformSuperAdmin, OrganizationAdmin, WorkspaceOwner, WorkspaceAdmin, ProjectManager, DepartmentManager, Supervisor, Reviewer, Approver, Contributor, Viewer, ExternalContractor.

Roles are presets, not the only authorization primitive.

## Permission examples
workspace.read, workspace.manage
project.read, project.manage
project.members.manage
form.create, form.publish, form.assign
submission.create, submission.read, submission.review
workflow.manage, workflow.act
report.read, report.export
domain_pack.install
integration.manage

## Scope
A grant contains principal, role/permission set, scope type, scope ID and optional constraints. Scope inheritance must be explicit.

## Authorization decision
`allow = authenticated AND tenant_match AND permission_granted AND policy_constraints_pass`
Default is deny.

## Requirements
- UI permissions are hints; server is authoritative.
- bulk endpoints evaluate each target scope safely.
- audit all role/grant changes.
- prohibit privilege escalation by delegated admins.
