from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from operations.contracts import Command

type NoticeTopic = Literal["work_assigned", "review_requested", "rule_notice"]
type NoticeSource = Literal["task", "workflow", "submission", "project"]


class Notice(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    recipient_id: UUID
    event_id: UUID
    run_id: UUID
    position: int = Field(ge=0, le=19)
    topic: NoticeTopic
    source_kind: NoticeSource
    source_id: UUID
    created_at: datetime


class ReadReceipt(Command):
    id: UUID
    organization_id: UUID
    notice_id: UUID
    recipient_id: UUID
    read_at: datetime


class InboxItem(Command):
    notice: Notice
    read_at: datetime | None


class NoticeStore(Protocol):
    def add(self, notice: Notice) -> None: ...
    def get(
        self, org: UUID, recipient: UUID, identifier: UUID, lock: bool = False
    ) -> Notice | None: ...
    def page(
        self, org: UUID, workspace: UUID, recipient: UUID, after: UUID | None
    ) -> list[Notice]: ...
    def receipt(self, org: UUID, notice: UUID) -> ReadReceipt | None: ...
    def add_receipt(self, receipt: ReadReceipt) -> None: ...
