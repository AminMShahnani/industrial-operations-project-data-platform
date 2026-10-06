from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ScopeType(StrEnum):
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"


class Role(StrEnum):
    ORGANIZATION_ADMIN = "OrganizationAdmin"
    WORKSPACE_OWNER = "WorkspaceOwner"
    WORKSPACE_ADMIN = "WorkspaceAdmin"
    VIEWER = "Viewer"
    CONTRIBUTOR = "Contributor"


PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ORGANIZATION_ADMIN: frozenset(
        {
            "organization.read",
            "organization.manage",
            "organization.members.manage",
            "workspace.read",
            "workspace.create",
            "workspace.manage",
            "iam.grants.manage",
            "form.read",
            "form.manage",
            "form.publish",
            "submission.create",
            "submission.read",
            "schedule.manage",
            "task.read",
            "task.execute",
            "project.create",
            "project.admin",
            "department.manage",
            "master_data.read",
            "master_data.manage",
        }
    ),
    Role.WORKSPACE_OWNER: frozenset(
        {
            "workspace.read",
            "workspace.manage",
            "iam.grants.manage",
            "form.read",
            "form.manage",
            "form.publish",
            "submission.create",
            "submission.read",
            "schedule.manage",
            "task.read",
            "task.execute",
            "project.create",
            "department.manage",
            "master_data.read",
            "master_data.manage",
        }
    ),
    Role.WORKSPACE_ADMIN: frozenset(
        {
            "workspace.read",
            "workspace.manage",
            "iam.grants.manage",
            "form.read",
            "form.manage",
            "form.publish",
            "submission.create",
            "submission.read",
            "schedule.manage",
            "task.read",
            "task.execute",
            "project.create",
            "department.manage",
            "master_data.read",
            "master_data.manage",
        }
    ),
    Role.VIEWER: frozenset({"organization.read", "workspace.read", "form.read", "task.read"}),
    Role.CONTRIBUTOR: frozenset(
        {"workspace.read", "form.read", "submission.create", "task.read", "task.execute"}
    ),
}


def role_permissions(role: Role, scope_type: ScopeType) -> frozenset[str]:
    if role == Role.VIEWER:
        return frozenset(
            {
                "organization.read" if scope_type == ScopeType.ORGANIZATION else "workspace.read",
                "master_data.read",
                "form.read",
                "task.read",
            }
        )
    return PERMISSIONS[role]


@dataclass(frozen=True)
class Scope:
    organization_id: UUID
    type: ScopeType
    id: UUID


@dataclass(frozen=True)
class Grant:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: Role
    scope_type: ScopeType
    scope_id: UUID
    inherit: bool
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    revoked: bool = False


def permissions(grants: list[Grant], user_id: UUID, scope: Scope, now: datetime) -> frozenset[str]:
    result: set[str] = set()
    for grant in grants:
        if (
            grant.organization_id != scope.organization_id
            or grant.user_id != user_id
            or grant.revoked
        ):
            continue
        if grant.valid_from is not None and now < grant.valid_from:
            continue
        if grant.valid_until is not None and now >= grant.valid_until:
            continue
        exact = grant.scope_type == scope.type and grant.scope_id == scope.id
        inherited = (
            grant.scope_type == ScopeType.ORGANIZATION
            and grant.scope_id == scope.organization_id
            and grant.inherit
            and scope.type == ScopeType.WORKSPACE
        )
        if exact or inherited:
            result.update(role_permissions(grant.role, grant.scope_type))
    return frozenset(result)
