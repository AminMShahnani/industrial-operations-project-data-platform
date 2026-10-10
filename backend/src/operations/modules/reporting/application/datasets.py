"""Permission-scoped reporting dataset projections."""

from typing import Protocol
from uuid import UUID

from operations.modules.identity.application.contracts import RequestContext
from operations.modules.reporting.application.contracts import OverdueTaskPage, OverdueTaskRow
from operations.modules.tasks.application.contracts import Task


class TaskInbox(Protocol):
    def inbox(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        view: str,
        mode: str,
        target: UUID | None,
        after: UUID | None,
    ) -> tuple[list[Task], UUID | None]: ...


class ReportingService:
    def __init__(self, tasks: TaskInbox) -> None:
        self.tasks = tasks

    def overdue_tasks(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        cursor: UUID | None,
    ) -> OverdueTaskPage:
        # Reuse the task module's live authorization and tenant-scoped query. Personal
        # mode intentionally limits rows to the caller's assignments.
        tasks, next_cursor = self.tasks.inbox(
            actor,
            organization_id,
            workspace_id,
            project_id,
            "overdue",
            "personal",
            None,
            cursor,
        )
        return OverdueTaskPage(
            items=[
                OverdueTaskRow(
                    id=task.id,
                    project_id=task.project_id,
                    kind=task.kind,
                    name=task.name,
                    state=task.state,
                    due_at=task.due_at,
                )
                for task in tasks
            ],
            next_cursor=next_cursor,
        )
