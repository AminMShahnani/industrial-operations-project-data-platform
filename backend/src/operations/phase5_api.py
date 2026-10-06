from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import EmailStr, Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command, ServiceError
from operations.modules.identity.application.contracts import User
from operations.modules.submissions.application.contracts import Submission
from operations.modules.workflows.application.contracts import (
    Workflow,
    WorkflowAction,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowRevision,
    WorkflowStep,
    WorkflowVersion,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}", tags=["workflows"]
)


class WorkflowCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    definition: WorkflowDefinition


class WorkflowSave(Command):
    expected_revision: int = Field(ge=1)
    definition: WorkflowDefinition


class WorkflowClone(Command):
    source_number: int = Field(ge=1)
    number: int = Field(ge=1)


class WorkflowActivation(Command):
    expected_revision: int = Field(ge=1)
    dry_run: bool = True
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ActionCommand(Command):
    expected_revision: int = Field(ge=1)
    idempotency_key: UUID
    kind: Literal["review", "approve", "return", "reject"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class RevisionCommand(Command):
    expected_revision: int = Field(ge=1)
    idempotency_key: UUID
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class WorkflowPage(Command):
    items: list[Workflow]
    next_cursor: UUID | None = None


class VersionPage(Command):
    items: list[WorkflowVersion]
    next_cursor: UUID | None = None


class InstancePage(Command):
    items: list[WorkflowInstance]
    next_cursor: UUID | None = None


class WorkflowHistory(Command):
    instance: WorkflowInstance
    steps: list[WorkflowStep]
    actions: list[WorkflowAction]
    available_actions: list[Literal["review", "approve", "return", "reject"]]
    revision: WorkflowRevision | None = None
    parent: WorkflowRevision | None = None
    available_revision: Literal["correction", "amendment"] | None = None
    next_step_cursor: int | None = None
    next_action_cursor: UUID | None = None


class CandidatePage(Command):
    items: list[User]


@router.get("/workflow-assignment-candidates", response_model=CandidatePage)
def candidates(
    organization_id: UUID,
    workspace_id: UUID,
    email: EmailStr,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
) -> CandidatePage:
    services.workflows.require(context, organization_id, workspace_id, project_id, True)
    row = Workflow(
        id=organization_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        name="Candidate scope",
    )
    users = services.authorization.identities.active_by_email(organization_id, str(email))
    return CandidatePage(
        items=[
            user
            for user in users[:100]
            if services.workflows.assignments.eligible(context, row, user, True)
        ]
    )


@router.post("/workflows", response_model=Workflow, status_code=201)
def create(
    organization_id: UUID,
    workspace_id: UUID,
    command: WorkflowCreate,
    context: Context,
    services: ServiceDependency,
) -> Workflow:
    return services.workflows.create(
        context, organization_id, workspace_id, command.project_id, command.name, command.definition
    )


@router.get("/workflows", response_model=WorkflowPage)
def workflows(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> WorkflowPage:
    services.workflows.require(context, organization_id, workspace_id, project_id, True)
    rows = services.workflows.store.list_workflows(
        organization_id, workspace_id, project_id, cursor
    )
    return WorkflowPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.get("/workflows/{workflow_id}/versions", response_model=VersionPage)
def versions(
    organization_id: UUID,
    workspace_id: UUID,
    workflow_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> VersionPage:
    services.workflows.get(context, organization_id, workspace_id, workflow_id, True)
    rows = services.workflows.store.versions(organization_id, workspace_id, workflow_id, cursor)
    return VersionPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.post("/workflows/{workflow_id}/versions", response_model=WorkflowVersion, status_code=201)
def clone(
    organization_id: UUID,
    workspace_id: UUID,
    workflow_id: UUID,
    command: WorkflowClone,
    context: Context,
    services: ServiceDependency,
) -> WorkflowVersion:
    return services.workflows.clone(
        context, organization_id, workspace_id, workflow_id, command.source_number, command.number
    )


@router.put("/workflows/{workflow_id}/versions/{number}", response_model=WorkflowVersion)
def save(
    organization_id: UUID,
    workspace_id: UUID,
    workflow_id: UUID,
    number: int,
    command: WorkflowSave,
    context: Context,
    services: ServiceDependency,
) -> WorkflowVersion:
    return services.workflows.save(
        context,
        organization_id,
        workspace_id,
        workflow_id,
        number,
        command.expected_revision,
        command.definition,
    )


@router.post("/workflows/{workflow_id}/versions/{number}/activate", response_model=WorkflowVersion)
def activate(
    organization_id: UUID,
    workspace_id: UUID,
    workflow_id: UUID,
    number: int,
    command: WorkflowActivation,
    context: Context,
    services: ServiceDependency,
) -> WorkflowVersion:
    return services.workflows.activate(
        context,
        organization_id,
        workspace_id,
        workflow_id,
        number,
        command.expected_revision,
        command.dry_run,
        command.expected_sha256,
    )


@router.get("/workflow-inbox", response_model=InstancePage)
def inbox(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> InstancePage:
    runtime = services.workflow_runtime
    services.workflows.require(context, organization_id, workspace_id, project_id)
    user = services.authorization.user(context, organization_id)
    rows = runtime.store.inbox(organization_id, workspace_id, user.id, project_id, cursor)
    visible = [row for row in rows[:100] if runtime.available_actions(context, row)]
    return InstancePage(items=visible, next_cursor=rows[99].id if len(rows) > 100 else None)


@router.get("/submissions/{submission_id}/workflow", response_model=WorkflowHistory)
def submission_workflow(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> WorkflowHistory:
    services.submissions.access(context, organization_id, workspace_id, submission_id)
    row = services.workflow_runtime.store.by_submission(
        organization_id, workspace_id, submission_id
    )
    if row is None:
        raise ServiceError(404, "workflow_not_started")
    return history(organization_id, workspace_id, row.id, context, services)


@router.get("/workflow-instances/{instance_id}", response_model=WorkflowHistory)
def history(
    organization_id: UUID,
    workspace_id: UUID,
    instance_id: UUID,
    context: Context,
    services: ServiceDependency,
    step_cursor: int | None = None,
    action_cursor: UUID | None = None,
) -> WorkflowHistory:
    if step_cursor is not None and not 1 <= step_cursor <= 1000:
        raise ServiceError(422, "invalid_workflow_step_cursor")
    runtime = services.workflow_runtime
    row = runtime.access(context, organization_id, workspace_id, instance_id)
    user = services.authorization.user(context, organization_id)
    workflow, _ = runtime.definition(context, row)
    owner = row.owner_id == user.id
    revision = (
        runtime.store.revision_by_source(organization_id, workspace_id, instance_id)
        if owner
        else None
    )
    available: Literal["correction", "amendment"] | None = None
    if (
        owner
        and not revision
        and "submission.create"
        in services.forms.permissions(context, organization_id, workspace_id, workflow.project_id)
    ):
        if row.state in {"returned", "rejected"}:
            available = "correction"
        elif row.state in {"approved", "closed"}:
            available = "amendment"
    steps = runtime.store.history_steps(organization_id, workspace_id, instance_id, step_cursor)
    actions = runtime.store.actions(organization_id, workspace_id, instance_id, action_cursor)
    return WorkflowHistory(
        instance=row,
        steps=steps[:20],
        actions=actions[:100],
        available_actions=runtime.available_actions(context, row),
        revision=revision,
        parent=runtime.store.revision_by_submission(
            organization_id, workspace_id, row.submission_id
        ),
        available_revision=available,
        next_step_cursor=steps[19].number if len(steps) > 20 else None,
        next_action_cursor=actions[99].id if len(actions) > 100 else None,
    )


@router.post("/workflow-instances/{instance_id}/actions", response_model=WorkflowInstance)
def act(
    organization_id: UUID,
    workspace_id: UUID,
    instance_id: UUID,
    command: ActionCommand,
    context: Context,
    services: ServiceDependency,
) -> WorkflowInstance:
    return services.workflow_runtime.act(
        context,
        organization_id,
        workspace_id,
        instance_id,
        command.expected_revision,
        command.idempotency_key,
        command.kind,
        command.reason,
    )


@router.post(
    "/workflow-instances/{instance_id}/revisions", response_model=Submission, status_code=201
)
def revise(
    organization_id: UUID,
    workspace_id: UUID,
    instance_id: UUID,
    command: RevisionCommand,
    context: Context,
    services: ServiceDependency,
) -> Submission:
    return services.workflow_runtime.create_revision(
        context,
        organization_id,
        workspace_id,
        instance_id,
        command.expected_revision,
        command.idempotency_key,
        command.reason,
    )
