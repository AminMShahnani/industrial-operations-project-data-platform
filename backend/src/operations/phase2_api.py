import base64
import binascii
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import AwareDatetime, EmailStr, Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command, ServiceError
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import User
from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataSchema,
    DataScope,
    DataType,
    ImportPreview,
    RecordStatus,
    RecordValues,
    RegistryKind,
)
from operations.modules.projects.application.contracts import (
    AnnotationPage,
    DepartmentProjectGrant,
    LifecycleDefinition,
    Project,
    ProjectContext,
    ProjectMembership,
    ProjectRole,
)
from operations.modules.workspaces.application.groups import Group, GroupKind, GroupMembership

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}",
    tags=["project and master data administration"],
)
WORKSPACE = "/workspaces/{workspace_id}"
PROJECT = WORKSPACE + "/projects/{project_id}"


class ProjectCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    context: ProjectContext = Field(default_factory=ProjectContext)
    lifecycle: LifecycleDefinition = Field(default_factory=LifecycleDefinition)


class ProjectUpdate(Command):
    name: str = Field(min_length=1, max_length=120)
    context: ProjectContext
    expected_version: int = Field(ge=1)


class ProjectTransition(Command):
    state: str = Field(min_length=1, max_length=40)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    dry_run: bool = True


class ProjectPage(Command):
    items: list[Project]
    next_cursor: UUID | None


class ProjectGrant(Command):
    role: ProjectRole
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class ProjectMemberCreate(ProjectGrant):
    user_id: UUID


class DepartmentGrantCreate(ProjectGrant):
    department_id: UUID


class GroupCreate(Command):
    kind: GroupKind
    name: str = Field(min_length=1, max_length=120)


class GroupUpdate(Command):
    name: str = Field(min_length=1, max_length=120)
    active: bool
    expected_version: int = Field(ge=1)


class GroupMemberCreate(Command):
    user_id: UUID
    manager: bool = False


class GroupPage(Command):
    items: list[Group]
    next_cursor: UUID | None


@router.post(WORKSPACE + "/projects", response_model=Project, status_code=201)
def create_project(
    organization_id: UUID,
    workspace_id: UUID,
    body: ProjectCreate,
    actor: Context,
    service: ServiceDependency,
) -> Project:
    return service.projects.create(
        actor, organization_id, workspace_id, body.name, body.context, body.lifecycle
    )


@router.get(WORKSPACE + "/projects", response_model=ProjectPage)
def list_projects(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
) -> ProjectPage:
    records = service.projects.list_projects(actor, organization_id, workspace_id, cursor)
    return ProjectPage(
        items=records[:100], next_cursor=records[99].id if len(records) > 100 else None
    )


@router.get(PROJECT, response_model=Project)
def read_project(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> Project:
    return service.projects.require_access(
        actor, organization_id, workspace_id, project_id, "project.read"
    )


@router.put(PROJECT, response_model=Project)
def update_project(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    body: ProjectUpdate,
    actor: Context,
    service: ServiceDependency,
) -> Project:
    return service.projects.update(
        actor,
        organization_id,
        workspace_id,
        project_id,
        body.name,
        body.context,
        body.expected_version,
    )


@router.get(PROJECT + "/annotations", response_model=AnnotationPage)
def project_annotations(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    actor: Context,
    service: ServiceDependency,
    kind: Literal["tag", "flag"] | None = None,
    cursor: UUID | None = None,
) -> AnnotationPage:
    return service.projects.annotations(
        actor, organization_id, workspace_id, project_id, kind, cursor
    )


@router.post(PROJECT + "/transitions", response_model=Project)
def transition(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    body: ProjectTransition,
    actor: Context,
    service: ServiceDependency,
) -> Project:
    return service.projects.transition(
        actor,
        organization_id,
        workspace_id,
        project_id,
        body.state,
        body.expected_version,
        body.reason,
        body.dry_run,
    )


@router.post(PROJECT + "/memberships", response_model=ProjectMembership, status_code=201)
def project_member(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    body: ProjectMemberCreate,
    actor: Context,
    service: ServiceDependency,
) -> ProjectMembership:
    return service.projects.add_member(
        actor,
        organization_id,
        workspace_id,
        project_id,
        body.user_id,
        body.role,
        body.valid_from,
        body.valid_until,
    )


@router.post(PROJECT + "/memberships/{membership_id}/revoke", status_code=204)
def revoke_project_member(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    membership_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> None:
    service.projects.revoke_member(actor, organization_id, workspace_id, project_id, membership_id)


@router.post(PROJECT + "/department-grants", response_model=DepartmentProjectGrant, status_code=201)
def department_grant(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    body: DepartmentGrantCreate,
    actor: Context,
    service: ServiceDependency,
) -> DepartmentProjectGrant:
    return service.projects.grant_department(
        actor,
        organization_id,
        workspace_id,
        project_id,
        body.department_id,
        body.role,
        body.valid_from,
        body.valid_until,
    )


@router.post(PROJECT + "/department-grants/{grant_id}/revoke", status_code=204)
def revoke_department(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    grant_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> None:
    service.projects.revoke_department(actor, organization_id, workspace_id, project_id, grant_id)


@router.post(WORKSPACE + "/groups", response_model=Group, status_code=201)
def create_group(
    organization_id: UUID,
    workspace_id: UUID,
    body: GroupCreate,
    actor: Context,
    service: ServiceDependency,
) -> Group:
    return service.groups.create(actor, organization_id, workspace_id, body.kind, body.name)


@router.get(WORKSPACE + "/groups", response_model=GroupPage)
def list_groups(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
) -> GroupPage:
    groups = service.groups.list_groups(actor, organization_id, workspace_id, cursor)
    return GroupPage(items=groups[:100], next_cursor=groups[99].id if len(groups) > 100 else None)


@router.put(WORKSPACE + "/groups/{group_id}", response_model=Group)
def update_group(
    organization_id: UUID,
    workspace_id: UUID,
    group_id: UUID,
    body: GroupUpdate,
    actor: Context,
    service: ServiceDependency,
) -> Group:
    return service.groups.update(
        actor,
        organization_id,
        workspace_id,
        group_id,
        body.name,
        body.active,
        body.expected_version,
    )


@router.post(
    WORKSPACE + "/groups/{group_id}/memberships", response_model=GroupMembership, status_code=201
)
def group_member(
    organization_id: UUID,
    workspace_id: UUID,
    group_id: UUID,
    body: GroupMemberCreate,
    actor: Context,
    service: ServiceDependency,
) -> GroupMembership:
    return service.groups.add_member(
        actor, organization_id, workspace_id, group_id, body.user_id, body.manager
    )


@router.post(WORKSPACE + "/groups/{group_id}/memberships/{membership_id}/revoke", status_code=204)
def revoke_group_member(
    organization_id: UUID,
    workspace_id: UUID,
    group_id: UUID,
    membership_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> None:
    service.groups.revoke(actor, organization_id, workspace_id, group_id, membership_id)


class DataTypeCreate(Command):
    scope: DataScope
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    registry: RegistryKind = RegistryKind.CUSTOM
    definition: DataSchema


class DataRecordCreate(Command):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    status: RecordStatus = RecordStatus.ACTIVE
    valid_from: date | None = None
    valid_until: date | None = None
    values: RecordValues = Field(default_factory=RecordValues)


class DataRecordUpdate(Command):
    name: str = Field(min_length=1, max_length=120)
    status: RecordStatus
    valid_from: date | None = None
    valid_until: date | None = None
    values: RecordValues
    expected_version: int = Field(ge=1)


class DataRecordPage(Command):
    items: list[DataRecord]
    next_cursor: UUID | None


class DataTypePage(Command):
    items: list[DataType]
    next_cursor: UUID | None


class PermissionHints(Command):
    permissions: list[str]


class MembershipCandidates(Command):
    items: list[User]


@router.get(PROJECT + "/membership-candidates", response_model=MembershipCandidates)
def project_candidates(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    email: EmailStr,
    actor: Context,
    service: ServiceDependency,
) -> MembershipCandidates:
    return MembershipCandidates(
        items=service.projects.membership_candidates(
            actor, organization_id, workspace_id, project_id, str(email)
        )
    )


@router.get(
    WORKSPACE + "/groups/{group_id}/membership-candidates", response_model=MembershipCandidates
)
def group_candidates(
    organization_id: UUID,
    workspace_id: UUID,
    group_id: UUID,
    email: EmailStr,
    actor: Context,
    service: ServiceDependency,
) -> MembershipCandidates:
    return MembershipCandidates(
        items=service.groups.membership_candidates(
            actor, organization_id, workspace_id, group_id, str(email)
        )
    )


@router.get(WORKSPACE + "/groups/{group_id}/permissions", response_model=PermissionHints)
def group_permissions(
    organization_id: UUID,
    workspace_id: UUID,
    group_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> PermissionHints:
    return PermissionHints(
        permissions=service.groups.management_permissions(
            actor, organization_id, workspace_id, group_id
        )
    )


@router.get("/master-data/types", response_model=DataTypePage)
def list_data_types(
    organization_id: UUID,
    actor: Context,
    service: ServiceDependency,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> DataTypePage:
    items, next_cursor = service.master_data.list_types(
        actor, organization_id, workspace_id, project_id, cursor
    )
    return DataTypePage(items=items, next_cursor=next_cursor)


@router.get(WORKSPACE + "/permissions", response_model=PermissionHints)
def workspace_permissions(
    organization_id: UUID, workspace_id: UUID, actor: Context, service: ServiceDependency
) -> PermissionHints:
    service.workspaces.read(actor, organization_id, workspace_id)
    return PermissionHints(
        permissions=sorted(
            service.authorization.allowed(
                actor, Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
            )
        )
    )


@router.get(PROJECT + "/permissions", response_model=PermissionHints)
def project_permissions(
    organization_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> PermissionHints:
    service.projects.require_access(
        actor, organization_id, workspace_id, project_id, "project.read"
    )
    return PermissionHints(
        permissions=sorted(
            service.projects.allowed(actor, organization_id, workspace_id, project_id)
        )
    )


class ImportRequest(Command):
    content_base64: str = Field(max_length=6 * 1024 * 1024)
    format: Literal["csv", "xlsx"]
    dry_run: bool = True
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_type_version: int = Field(ge=1)


@router.post("/master-data/types", response_model=DataType, status_code=201)
def create_data_type(
    organization_id: UUID, body: DataTypeCreate, actor: Context, service: ServiceDependency
) -> DataType:
    return service.master_data.create_type(
        actor,
        organization_id,
        body.scope,
        body.workspace_id,
        body.project_id,
        body.code,
        body.name,
        body.registry,
        body.definition,
    )


@router.get("/master-data/types/{type_id}", response_model=DataType)
def read_data_type(
    organization_id: UUID, type_id: UUID, actor: Context, service: ServiceDependency
) -> DataType:
    return service.master_data.definition(actor, organization_id, type_id)


@router.post("/master-data/types/{type_id}/records", response_model=DataRecord, status_code=201)
def create_record(
    organization_id: UUID,
    type_id: UUID,
    body: DataRecordCreate,
    actor: Context,
    service: ServiceDependency,
) -> DataRecord:
    return service.master_data.create_record(
        actor,
        organization_id,
        type_id,
        body.code,
        body.name,
        body.status,
        body.valid_from,
        body.valid_until,
        body.values,
    )


@router.put("/master-data/types/{type_id}/records/{record_id}", response_model=DataRecord)
def update_record(
    organization_id: UUID,
    type_id: UUID,
    record_id: UUID,
    body: DataRecordUpdate,
    actor: Context,
    service: ServiceDependency,
) -> DataRecord:
    return service.master_data.update_record(
        actor,
        organization_id,
        type_id,
        record_id,
        body.name,
        body.status,
        body.valid_from,
        body.valid_until,
        body.values,
        body.expected_version,
    )


@router.get("/master-data/types/{type_id}/records", response_model=DataRecordPage)
def list_records(
    organization_id: UUID,
    type_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
) -> DataRecordPage:
    definition = service.master_data.definition(actor, organization_id, type_id)
    records = service.master_data.store.list_records(definition.organization_id, type_id, cursor)
    return DataRecordPage(
        items=records[:100], next_cursor=records[99].id if len(records) > 100 else None
    )


@router.post("/master-data/types/{type_id}/imports", response_model=ImportPreview)
def import_records(
    organization_id: UUID,
    type_id: UUID,
    body: ImportRequest,
    actor: Context,
    service: ServiceDependency,
) -> ImportPreview:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except binascii.Error as error:
        raise ServiceError(422, "invalid_import_file") from error
    return service.master_transfer.import_records(
        actor,
        organization_id,
        type_id,
        content,
        body.format,
        body.dry_run,
        body.expected_sha256,
        body.expected_type_version,
    )


@router.get(
    "/master-data/types/{type_id}/export",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
            "headers": {"X-Next-Cursor": {"schema": {"type": "string", "format": "uuid"}}},
        }
    },
)
def export_records(
    organization_id: UUID,
    type_id: UUID,
    actor: Context,
    service: ServiceDependency,
    format: Literal["csv", "xlsx"] = "csv",
    cursor: UUID | None = None,
) -> Response:
    content, next_cursor = service.master_transfer.export_records(
        actor, organization_id, type_id, format, cursor
    )
    media_type = (
        "text/csv"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    headers = {"Content-Disposition": f'attachment; filename="master-data.{format}"'}
    if next_cursor:
        headers["X-Next-Cursor"] = str(next_cursor)
    return Response(content=content, media_type=media_type, headers=headers)
