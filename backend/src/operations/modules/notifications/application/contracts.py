from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

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
    run_id: UUID | None = None
    position: int | None = Field(default=None, ge=0, le=19)
    origin: Literal["automation", "automatic"] = "automation"
    source_intent_id: UUID | None = None
    topic: NoticeTopic
    source_kind: NoticeSource
    source_id: UUID
    created_at: datetime

    @model_validator(mode="after")
    def coherent(self) -> Notice:
        if self.created_at.utcoffset() is None:
            raise ValueError("notification_timestamp_requires_timezone")
        if self.origin == "automation":
            if self.run_id is None or self.position is None or self.source_intent_id is not None:
                raise ValueError("notification_automation_binding_required")
        elif (
            self.run_id is not None
            or self.position is not None
            or self.source_intent_id is None
            or self.source_kind not in {"task", "workflow"}
        ):
            raise ValueError("notification_automatic_binding_required")
        return self


class ReadReceipt(Command):
    id: UUID
    organization_id: UUID
    notice_id: UUID
    recipient_id: UUID
    read_at: datetime


class InboxItem(Command):
    notice: Notice
    read_at: datetime | None


class NotificationAttempt(Command):
    id: UUID
    organization_id: UUID
    delivery_id: UUID
    number: int = Field(ge=1, le=20)
    outcome: Literal["completed", "retry", "dead_letter"]
    created: int = Field(ge=0, le=1000)
    skipped: int = Field(ge=0, le=1000)
    error_code: str | None = None
    occurred_at: datetime


class NoticeStore(Protocol):
    def add_attempt(self, attempt: NotificationAttempt) -> None: ...
    def add(self, notice: Notice) -> None: ...
    def get(
        self, org: UUID, recipient: UUID, identifier: UUID, lock: bool = False
    ) -> Notice | None: ...
    def page(
        self, org: UUID, workspace: UUID, recipient: UUID, after: UUID | None
    ) -> list[Notice]: ...
    def receipt(self, org: UUID, notice: UUID) -> ReadReceipt | None: ...
    def add_receipt(self, receipt: ReadReceipt) -> None: ...
