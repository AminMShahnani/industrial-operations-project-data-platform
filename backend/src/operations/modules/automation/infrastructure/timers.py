from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.automation.application.timers import TimerOccurrence
from operations.platform.database import Base


class TimerOccurrenceRow(Base):
    __tablename__ = "automation_timer_occurrences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "rule_version_id"],
            ["automation_versions.organization_id", "automation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "id"], ["outbox_events.organization_id", "outbox_events.id"]
        ),
        UniqueConstraint(
            "organization_id", "rule_version_id", "scheduled_at", name="uq_timer_slot_once"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    rule_version_id: Mapped[UUID]
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TimerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def last(self, org: UUID, version: UUID) -> datetime | None:
        return self.session.scalar(
            select(func.max(TimerOccurrenceRow.scheduled_at)).where(
                TimerOccurrenceRow.organization_id == org,
                TimerOccurrenceRow.rule_version_id == version,
            )
        )

    def add(self, row: TimerOccurrence) -> None:
        self.session.add(TimerOccurrenceRow(**row.model_dump()))
        self.session.flush()
