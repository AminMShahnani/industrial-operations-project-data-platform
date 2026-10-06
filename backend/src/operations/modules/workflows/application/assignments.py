from datetime import UTC, datetime
from uuid import UUID

from operations.contracts import ServiceError
from operations.modules.forms.application.contracts import FormValues
from operations.modules.identity.application.contracts import Principal, RequestContext, User
from operations.modules.projects.application.contracts import ProjectRole
from operations.modules.projects.application.service import effective
from operations.modules.scheduling.application.service import SchedulingService
from operations.modules.workflows.application.contracts import Assignment, Workflow


class AssignmentResolver:
    def __init__(self, scheduling: SchedulingService) -> None:
        self.scheduling, self.forms = scheduling, scheduling.forms

    def eligible(
        self,
        actor: RequestContext,
        row: Workflow,
        user: User,
        approve: bool,
        notification: bool = False,
    ) -> bool:
        try:
            context = RequestContext(
                Principal(user.issuer, user.subject), actor.request_id, actor.correlation_id
            )
            permissions = self.forms.permissions(
                context, row.organization_id, row.workspace_id, row.project_id
            )
            return (
                user.active
                and (
                    {"workflow.read"}
                    if notification
                    else {"workflow.act", "submission.approve" if approve else "submission.review"}
                )
                <= permissions
            )
        except ServiceError:
            return False

    def matches(
        self,
        actor: RequestContext,
        row: Workflow,
        user: User,
        target: Assignment,
        values: FormValues | None,
    ) -> bool:
        org, workspace, project = row.organization_id, row.workspace_id, row.project_id
        if target.kind == "user":
            return user.id == target.target_id
        if target.kind == "submission_field":
            value = values.fields.get(target.field_key or "") if values else None
            return isinstance(value, str) and value == str(user.id)
        if target.kind == "manager_of":
            raise ServiceError(422, "manager_relationship_unavailable")
        if target.kind == "project_role":
            return project is not None and self.scheduling.has_role(
                actor, org, workspace, project, user, str(target.role)
            )
        if target.target_id is None:
            return False
        group = self.forms.groups.get(org, workspace, target.target_id)
        if not group.active or group.kind.value != (
            "team" if target.kind == "team" else "department"
        ):
            return False
        if not any(
            member.group_id == group.id
            for member in self.forms.groups.store.memberships(org, workspace, user.id)
        ):
            return False
        if target.kind == "team":
            return True
        return project is not None and any(
            grant.project_id == project
            and grant.department_id == group.id
            and str(grant.role) == target.role
            and effective(grant, datetime.now(UTC))
            for grant in self.forms.projects.store.department_grants(org, [group.id])
        )

    def check_target(self, row: Workflow, target: Assignment, user_fields: set[str]) -> None:
        if target.kind == "manager_of":
            raise ServiceError(422, "manager_relationship_unavailable")
        if target.kind in {"project_role", "department_role"} and (
            row.project_id is None or target.role not in {role.value for role in ProjectRole}
        ):
            raise ServiceError(422, "workflow_project_role_required")
        if target.kind == "submission_field" and target.field_key not in user_fields:
            raise ServiceError(422, "workflow_assignment_requires_user_field")
        if target.kind in {"team", "department_role"} and target.target_id:
            group = self.forms.groups.get(row.organization_id, row.workspace_id, target.target_id)
            if not group.active or group.kind.value != (
                "team" if target.kind == "team" else "department"
            ):
                raise ServiceError(422, "workflow_assignment_group_invalid")
        if target.kind == "user" and target.target_id:
            user = self.forms.authorization.identities.by_id(row.organization_id, target.target_id)
            if not user or not user.active:
                raise ServiceError(422, "workflow_assignment_user_invalid")

    def resolve(
        self,
        actor: RequestContext,
        row: Workflow,
        assignments: list[Assignment],
        approve: bool,
        values: FormValues | None = None,
        notification: bool = False,
    ) -> list[UUID]:
        output: list[UUID] = []
        for target in assignments:
            after: UUID | None = None
            matches: list[UUID] = []
            while True:
                users = self.forms.authorization.identities.active_users(row.organization_id, after)
                for user in users[:100]:
                    if (
                        user.id not in output
                        and self.matches(actor, row, user, target, values)
                        and self.eligible(actor, row, user, approve, notification)
                    ):
                        matches.append(user.id)
                if len(matches) + len(output) > 1000:
                    raise ServiceError(422, "workflow_recipient_limit")
                if len(users) <= 100:
                    break
                after = users[99].id
            output.extend(user for user in sorted(matches) if user not in output)
        return output
