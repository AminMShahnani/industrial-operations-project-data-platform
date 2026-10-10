from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from operations.contracts import Command
from operations.modules.tasks.application.contracts import TaskState


class OverdueTaskRow(Command):
    id: UUID
    project_id: UUID | None
    kind: Literal["form", "generic"]
    name: str
    state: TaskState
    due_at: AwareDatetime


class OverdueTaskPage(Command):
    items: list[OverdueTaskRow] = Field(max_length=100)
    next_cursor: UUID | None
