from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    select,
    tuple_,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.contracts import ServiceError
from operations.modules.notifications.application.contracts import Notice, ReadReceipt
from operations.platform.database import Base


class NoticeRow(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "recipient_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["outbox_events.organization_id", "outbox_events.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["automation_runs.organization_id", "automation_runs.id"]
        ),
        UniqueConstraint("organization_id", "id", "recipient_id", name="uq_notice_recipient"),
        UniqueConstraint(
            "organization_id", "run_id", "position", "recipient_id", name="uq_notice_action_once"
        ),
        CheckConstraint(
            "position BETWEEN 0 AND 19 "
            "AND topic IN ('work_assigned','review_requested','rule_notice') "
            "AND source_kind IN ('task','workflow','submission','project')",
            name="notice_contract",
        ),
        Index(
            "ix_notice_recipient_cursor",
            "organization_id",
            "workspace_id",
            "recipient_id",
            "created_at",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    recipient_id: Mapped[UUID]
    event_id: Mapped[UUID]
    run_id: Mapped[UUID]
    position: Mapped[int]
    topic: Mapped[str] = mapped_column(String(30))
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReadRow(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "notice_id", "recipient_id"],
            ["notifications.organization_id", "notifications.id", "notifications.recipient_id"],
        ),
        UniqueConstraint("organization_id", "notice_id", name="uq_notice_read_once"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    notice_id: Mapped[UUID]
    recipient_id: Mapped[UUID]
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def notice_value(row: NoticeRow) -> Notice:
    return Notice.model_validate({key: getattr(row, key) for key in Notice.model_fields})


class NoticeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, notice: Notice) -> None:
        self.session.add(NoticeRow(**notice.model_dump()))
        self.session.flush()

    def get(
        self, org: UUID, recipient: UUID, identifier: UUID, lock: bool = False
    ) -> Notice | None:
        statement = select(NoticeRow).where(
            NoticeRow.organization_id == org,
            NoticeRow.recipient_id == recipient,
            NoticeRow.id == identifier,
        )
        if lock:
            statement = statement.with_for_update()
        row = self.session.scalar(statement)
        return notice_value(row) if row else None

    def page(self, org: UUID, workspace: UUID, recipient: UUID, after: UUID | None) -> list[Notice]:
        statement = select(NoticeRow).where(
            NoticeRow.organization_id == org,
            NoticeRow.workspace_id == workspace,
            NoticeRow.recipient_id == recipient,
        )
        if after:
            cursor = self.session.scalar(statement.where(NoticeRow.id == after))
            if cursor is None:
                raise ServiceError(422, "notification_cursor_invalid")
            statement = statement.where(
                tuple_(NoticeRow.created_at, NoticeRow.id) > (cursor.created_at, cursor.id)
            )
        return [
            notice_value(row)
            for row in self.session.scalars(
                statement.order_by(NoticeRow.created_at, NoticeRow.id).limit(101)
            )
        ]

    def receipt(self, org: UUID, notice: UUID) -> ReadReceipt | None:
        row = self.session.scalar(
            select(ReadRow).where(ReadRow.organization_id == org, ReadRow.notice_id == notice)
        )
        return (
            ReadReceipt.model_validate({key: getattr(row, key) for key in ReadReceipt.model_fields})
            if row
            else None
        )

    def add_receipt(self, receipt: ReadReceipt) -> None:
        self.session.add(ReadRow(**receipt.model_dump()))
        self.session.flush()
