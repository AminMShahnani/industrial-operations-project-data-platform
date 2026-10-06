from datetime import datetime, time
from typing import Literal
from uuid import UUID, uuid7

from fastapi import APIRouter
from pydantic import Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.projects.application.contracts import Milestone
from operations.modules.scheduling.application.contracts import (
    Schedule,
    ScheduleDefinition,
    ScheduleVersion,
    Shift,
    Trigger,
)
from operations.modules.tasks.application.contracts import Reminder, Task

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}",
    tags=["scheduling and tasks"],
)


class ScheduleCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    definition: ScheduleDefinition


class VersionSave(Command):
    expected_revision: int = Field(ge=1)
    definition: ScheduleDefinition


class Clone(Command):
    source_number: int = Field(ge=1)
    number: int = Field(ge=1)


class Activate(Command):
    expected_revision: int = Field(ge=1)
    dry_run: bool = True
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Lifecycle(Command):
    expected_revision: int = Field(ge=1)
    dry_run: bool = True
    state: Literal["active", "paused", "retired"]
    reason: str = Field(min_length=1, max_length=500)


class Materialize(Command):
    start: datetime
    end: datetime
    dry_run: bool = True


class MaterializationResult(Command):
    planned: int
    created: int


class TaskClaim(Command):
    expected_revision: int = Field(ge=1)


class TaskCancel(Command):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    dry_run: bool = True


class SchedulePage(Command):
    items: list[Schedule]
    next_cursor: UUID | None


class ScheduleVersionPage(Command):
    items: list[ScheduleVersion]
    next_cursor: UUID | None


class TaskPage(Command):
    items: list[Task]
    next_cursor: UUID | None


class ShiftCreate(Command):
    project_id: UUID | None = None
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(max_length=80)
    starts_at: time
    duration_seconds: int = Field(ge=3600, le=86400)
    user_ids: list[UUID] = Field(min_length=1, max_length=1000)


class ShiftPage(Command):
    items: list[Shift]
    next_cursor: UUID | None


class MilestoneCreate(Command):
    project_id: UUID
    name: str = Field(min_length=1, max_length=120)
    planned_at: datetime


class TriggerCreate(Command):
    idempotency_key: UUID
    project_id: UUID | None = None
    code: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,59}$")
    occurred_at: datetime


class ReminderPage(Command):
    items: list[Reminder]
    next_cursor: UUID | None


class ReminderGeneration(Command):
    project_id: UUID | None = None
    cursor: UUID | None = None


class ReminderResult(Command):
    created: int
    next_cursor: UUID | None


@router.post("/schedules", response_model=Schedule, status_code=201)
def create_schedule(
    organization_id: UUID,
    workspace_id: UUID,
    command: ScheduleCreate,
    context: Context,
    services: ServiceDependency,
) -> Schedule:
    return services.scheduling.create(
        context, organization_id, workspace_id, command.project_id, command.name, command.definition
    )


@router.get("/schedules", response_model=SchedulePage)
def schedules(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> SchedulePage:
    services.scheduling.require(context, organization_id, workspace_id, project_id)
    rows = services.scheduling.store.list_schedules(
        organization_id, workspace_id, project_id, cursor
    )
    return SchedulePage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.get("/schedules/{schedule_id}/versions", response_model=ScheduleVersionPage)
def versions(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> ScheduleVersionPage:
    services.scheduling.get(context, organization_id, workspace_id, schedule_id, True)
    rows = services.scheduling.store.versions(organization_id, schedule_id, cursor)
    return ScheduleVersionPage(
        items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None
    )


@router.get("/schedules/{schedule_id}/versions/{number}", response_model=ScheduleVersion)
def version(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    number: int,
    context: Context,
    services: ServiceDependency,
) -> ScheduleVersion:
    return services.scheduling.version(context, organization_id, workspace_id, schedule_id, number)[
        1
    ]


@router.put("/schedules/{schedule_id}/versions/{number}", response_model=ScheduleVersion)
def save_version(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    number: int,
    command: VersionSave,
    context: Context,
    services: ServiceDependency,
) -> ScheduleVersion:
    return services.scheduling.save(
        context,
        organization_id,
        workspace_id,
        schedule_id,
        number,
        command.expected_revision,
        command.definition,
    )


@router.post("/schedules/{schedule_id}/versions", response_model=ScheduleVersion, status_code=201)
def clone_version(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    command: Clone,
    context: Context,
    services: ServiceDependency,
) -> ScheduleVersion:
    return services.scheduling.clone(
        context, organization_id, workspace_id, schedule_id, command.source_number, command.number
    )


@router.post("/schedules/{schedule_id}/versions/{number}/activate", response_model=ScheduleVersion)
def activate(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    number: int,
    command: Activate,
    context: Context,
    services: ServiceDependency,
) -> ScheduleVersion:
    services.tasks.supersede(context, organization_id, workspace_id, schedule_id, number, True)
    row = services.scheduling.activate(
        context,
        organization_id,
        workspace_id,
        schedule_id,
        number,
        command.expected_revision,
        command.dry_run,
        command.expected_sha256,
    )
    if not command.dry_run:
        services.tasks.supersede(context, organization_id, workspace_id, schedule_id, number)
    return row


@router.post("/schedules/{schedule_id}/versions/{number}/lifecycle", response_model=ScheduleVersion)
def lifecycle(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    number: int,
    command: Lifecycle,
    context: Context,
    services: ServiceDependency,
) -> ScheduleVersion:
    return services.scheduling.lifecycle(
        context,
        organization_id,
        workspace_id,
        schedule_id,
        number,
        command.expected_revision,
        command.state,
        command.reason,
        command.dry_run,
    )


@router.post("/schedules/{schedule_id}/materialize", response_model=MaterializationResult)
def materialize(
    organization_id: UUID,
    workspace_id: UUID,
    schedule_id: UUID,
    command: Materialize,
    context: Context,
    services: ServiceDependency,
) -> MaterializationResult:
    planned, created = services.tasks.materialize(
        context,
        organization_id,
        workspace_id,
        schedule_id,
        command.start,
        command.end,
        command.dry_run,
    )
    return MaterializationResult(planned=planned, created=created)


@router.get("/tasks", response_model=TaskPage)
def inbox(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    view: Literal["all", "due_today", "overdue", "upcoming", "returned", "awaiting_review"] = "all",
    mode: Literal["personal", "team", "department", "project"] = "personal",
    target_id: UUID | None = None,
    cursor: UUID | None = None,
) -> TaskPage:
    rows, after = services.tasks.inbox(
        context, organization_id, workspace_id, project_id, view, mode, target_id, cursor
    )
    return TaskPage(items=rows, next_cursor=after)


@router.get("/tasks/{task_id}", response_model=Task)
def task(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    context: Context,
    services: ServiceDependency,
) -> Task:
    return services.tasks.public(
        context, services.tasks.access(context, organization_id, workspace_id, task_id)
    )


@router.post("/tasks/{task_id}/start", response_model=Task)
def claim(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    command: TaskClaim,
    context: Context,
    services: ServiceDependency,
) -> Task:
    return services.tasks.public(
        context,
        services.tasks.claim(
            context, organization_id, workspace_id, task_id, command.expected_revision
        ),
    )


@router.post("/tasks/{task_id}/cancel", response_model=Task)
def cancel(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    command: TaskCancel,
    context: Context,
    services: ServiceDependency,
) -> Task:
    return services.tasks.public(
        context,
        services.tasks.cancel(
            context,
            organization_id,
            workspace_id,
            task_id,
            command.expected_revision,
            command.reason,
            command.dry_run,
        ),
    )


@router.post("/shifts", response_model=Shift, status_code=201)
def shift_create(
    organization_id: UUID,
    workspace_id: UUID,
    command: ShiftCreate,
    context: Context,
    services: ServiceDependency,
) -> Shift:
    row = Shift(
        id=uuid7(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        **command.model_dump(),
    )
    return services.scheduling.add_shift(context, row)


@router.get("/shifts", response_model=ShiftPage)
def shifts(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> ShiftPage:
    services.scheduling.require(context, organization_id, workspace_id, project_id, True)
    rows = services.scheduling.store.shifts(organization_id, workspace_id, project_id, cursor)
    return ShiftPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.post("/milestones", response_model=Milestone, status_code=201)
def milestone(
    organization_id: UUID,
    workspace_id: UUID,
    command: MilestoneCreate,
    context: Context,
    services: ServiceDependency,
) -> Milestone:
    return services.scheduling.add_milestone(
        context,
        Milestone(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            **command.model_dump(),
        ),
    )


@router.post("/schedule-triggers", response_model=Trigger)
def trigger(
    organization_id: UUID,
    workspace_id: UUID,
    command: TriggerCreate,
    context: Context,
    services: ServiceDependency,
) -> Trigger:
    return services.scheduling.add_trigger(
        context,
        Trigger(
            id=command.idempotency_key,
            organization_id=organization_id,
            workspace_id=workspace_id,
            **command.model_dump(exclude={"idempotency_key"}),
        ),
    )


@router.post("/task-reminders/generate", response_model=ReminderResult)
def generate_reminders(
    organization_id: UUID,
    workspace_id: UUID,
    command: ReminderGeneration,
    context: Context,
    services: ServiceDependency,
) -> ReminderResult:
    count, after = services.tasks.generate_reminders(
        context, organization_id, workspace_id, command.project_id, command.cursor
    )
    return ReminderResult(created=count, next_cursor=after)


@router.get("/tasks/{task_id}/reminders", response_model=ReminderPage)
def reminders(
    organization_id: UUID,
    workspace_id: UUID,
    task_id: UUID,
    context: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> ReminderPage:
    services.tasks.access(context, organization_id, workspace_id, task_id)
    rows = services.tasks.store.reminders(organization_id, workspace_id, task_id, cursor)
    return ReminderPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)
