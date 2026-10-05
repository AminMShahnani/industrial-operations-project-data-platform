# Domain Model

## Aggregate overview
Organization
- Workspaces
- Users/Memberships
- DomainPackInstallations
- OrganizationSettings

Workspace
- Departments
- Teams
- Projects
- WorkspaceMemberships
- SharedTemplates
- MasterDataSets

Project
- ProjectMemberships
- DepartmentProjectGrants
- ProjectPhases/Milestones
- Assets/Sites/DomainEntities
- FormAssignments
- Workflows
- Schedules
- Tasks
- Reports

Form
- FormDefinition
- FormVersion
- ComponentReferences
- ValidationRules
- FormulaDefinitions

Operational execution
Schedule -> TaskOccurrence -> Submission -> WorkflowInstance -> WorkflowSteps/Decisions

## Identity rule
Users are organization identities. Access to workspace/project resources is granted through memberships and policies. A user may hold different roles in different scopes.

## Ownership rule
Projects belong to workspaces. Departments do not own projects; they receive grants to projects.

## Versioning rule
Published FormVersion, WorkflowVersion, AutomationRuleVersion and PackVersion artifacts are immutable. New behavior requires a new version.

## Submission rule
A submission always references an exact form version and records the relevant project/workspace/organization scope at submission time.
