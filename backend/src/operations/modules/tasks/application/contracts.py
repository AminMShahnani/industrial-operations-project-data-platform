from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

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
]


class Task(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    schedule_id: UUID
    schedule_version_id: UUID
    schedule_number: int
    form_id: UUID
    form_version_id: UUID
    form_number: int
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
