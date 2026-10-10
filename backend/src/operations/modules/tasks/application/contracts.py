from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.scheduling.application.contracts import Assignment

TaskState = Literal[
    "open",
    "in_progress",
    "submitted",
    "awaiting_review",
    "returned",
    "approved",
    "cancelled",
    "superseded",
    "completed",
]


class GenericTaskDefinition(Command):
    origin_id: UUID
    name: str = Field(min_length=1, max_length=120)
    assignments: list[Assignment] = Field(min_length=1, max_length=20)
    occurs_at: datetime
    due_seconds: int = Field(ge=60, le=2592000)

    @model_validator(mode="after")
    def coherent(self) -> GenericTaskDefinition:
        if self.occurs_at.utcoffset() is None:
            raise ValueError("task_timezone_required")
        if len({item.key() for item in self.assignments}) != len(self.assignments):
            raise ValueError("duplicate_task_assignment")
        return self


class Task(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    kind: Literal["form", "generic"] = "form"
    origin_id: UUID | None = None
    schedule_id: UUID | None = None
    schedule_version_id: UUID | None = None
    schedule_number: int | None = None
    form_id: UUID | None = None
    form_version_id: UUID | None = None
    form_number: int | None = None
    name: str
    timezone: str
    occurs_at: datetime
    due_at: datetime
    assignment: Assignment
    assignment_key: str
    recipient_ids: list[UUID]
    reminder_offsets: list[int]
    state: TaskState = "open"
    claimant_id: UUID | None = None
    submission_id: UUID | None = None
    revision: int = 1
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def coherent(self) -> Task:
        pins = (
            self.schedule_id,
            self.schedule_version_id,
            self.schedule_number,
            self.form_id,
            self.form_version_id,
            self.form_number,
        )
        if self.kind == "form":
            if any(pin is None for pin in pins) or self.origin_id is not None:
                raise ValueError("form_task_pins_required")
            if self.completed_at is not None or self.state == "completed":
                raise ValueError("form_task_completion_requires_submission")
        elif (
            any(pin is not None for pin in pins)
            or self.origin_id is None
            or self.submission_id is not None
            or self.state not in {"open", "in_progress", "completed", "cancelled"}
            or ((self.state == "completed") != (self.completed_at is not None))
        ):
            raise ValueError("invalid_generic_task")
        return self


class Reminder(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    task_id: UUID
    offset_seconds: int
    scheduled_at: datetime
    created_at: datetime


class DeadlineEvent(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    task_id: UUID
    kind: Literal["due", "overdue"]
    scheduled_at: datetime


class DeadlineTick(Command):
    candidates: int
    created: int
    cursor: UUID | None = None


class TaskStore(Protocol):
    def reminder_intents(
        self, org: UUID, workspace: UUID, after: UUID | None
    ) -> list[Reminder]: ...
    def deadline_candidates(
        self,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        now: datetime,
        after: UUID | None,
        lock: bool,
    ) -> list[Task]: ...
    def deadline_kinds(self, org: UUID, workspace: UUID, task: UUID) -> set[str]: ...
    def add_deadline(self, row: DeadlineEvent) -> bool: ...
    def by_submission(self, org: UUID, workspace: UUID, submission: UUID) -> Task | None: ...
    def add(self, row: Task) -> bool: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Task | None: ...
    def save(self, row: Task, expected: int) -> bool: ...
    def list_tasks(
        self,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        user: UUID | None,
        assignment: str | None,
        view: str,
        start: datetime,
        end: datetime,
        after: UUID | None,
    ) -> list[Task]: ...
    def future_open(
        self, org: UUID, workspace: UUID, schedule: UUID, before_number: int, now: datetime
    ) -> list[Task]: ...
    def reminder_candidates(
        self, org: UUID, workspace: UUID, project: UUID | None, now: datetime, after: UUID | None
    ) -> list[Task]: ...
    def add_reminder(self, row: Reminder) -> bool: ...
    def reminders(
        self, org: UUID, workspace: UUID, task: UUID, after: UUID | None
    ) -> list[Reminder]: ...
