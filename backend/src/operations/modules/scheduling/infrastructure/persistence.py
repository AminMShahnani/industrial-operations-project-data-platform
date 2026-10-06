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
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.scheduling.application.contracts import (
    Schedule,
    ScheduleVersion,
    Shift,
    Trigger,
)
from operations.platform.database import Base


class ScheduleRow(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("organization_id", "workspace_id", "id", name="uq_schedules_scope"),
        CheckConstraint(
            "revision > 0 AND (active_number IS NULL OR active_number > 0)",
            name="schedule_revision",
        ),
        Index("ix_schedules_scope_cursor", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(120))
    active_number: Mapped[int | None]
    revision: Mapped[int]


class ScheduleVersionRow(Base):
    __tablename__ = "schedule_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "schedule_id"],
            ["schedules.organization_id", "schedules.workspace_id", "schedules.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_version_id"],
            ["form_versions.organization_id", "form_versions.workspace_id", "form_versions.id"],
        ),
        UniqueConstraint(
            "organization_id", "schedule_id", "number", name="uq_schedule_version_number"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "schedule_id",
            "id",
            "number",
            name="uq_schedule_version_exact",
        ),
        CheckConstraint(
            "number > 0 AND revision > 0 AND state IN ('draft','active','paused','retired')",
            name="schedule_version_state",
        ),
        CheckConstraint(
            "(state='draft' AND activated_at IS NULL AND content_sha256 IS NULL "
            "AND form_version_id IS NULL) OR (state<>'draft' AND activated_at IS NOT NULL "
            "AND content_sha256 IS NOT NULL AND form_version_id IS NOT NULL)",
            name="schedule_activation",
        ),
        Index("ix_schedule_versions_cursor", "organization_id", "schedule_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    schedule_id: Mapped[UUID]
    number: Mapped[int]
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int]
    form_version_id: Mapped[UUID | None]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class ShiftRow(Base):
    __tablename__ = "schedule_shifts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "code", "number", name="uq_shift_code_number"
        ),
        Index("ix_shifts_scope_cursor", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    code: Mapped[str] = mapped_column(String(60))
    number: Mapped[int]
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)


class TriggerRow(Base):
    __tablename__ = "schedule_triggers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        Index(
            "ix_schedule_triggers_scope_time",
            "organization_id",
            "workspace_id",
            "project_id",
            "code",
            "occurred_at",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    code: Mapped[str] = mapped_column(String(60))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScheduleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, row: Schedule) -> None:
        self.session.add(ScheduleRow(**row.model_dump()))
        self.session.flush()

    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Schedule | None:
        row = self.session.scalar(
            select(ScheduleRow)
            .where(
                ScheduleRow.organization_id == org,
                ScheduleRow.workspace_id == workspace,
                ScheduleRow.id == identifier,
            )
            .with_for_update()
        )
        return (
            Schedule.model_validate({k: getattr(row, k) for k in Schedule.model_fields})
            if row
            else None
        )

    def update(self, row: Schedule, expected: int) -> bool:
        result = self.session.execute(
            update(ScheduleRow)
            .returning(ScheduleRow.id)
            .where(
                ScheduleRow.organization_id == row.organization_id,
                ScheduleRow.id == row.id,
                ScheduleRow.revision == expected,
            )
            .values(active_number=row.active_number, revision=row.revision)
        )
        return result.scalar_one_or_none() is not None

    def list_schedules(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Schedule]:
        query = select(ScheduleRow).where(
            ScheduleRow.organization_id == org,
            ScheduleRow.workspace_id == workspace,
            ScheduleRow.project_id == project,
        )
        if after:
            query = query.where(ScheduleRow.id > after)
        return [
            Schedule.model_validate({k: getattr(row, k) for k in Schedule.model_fields})
            for row in self.session.scalars(query.order_by(ScheduleRow.id).limit(101))
        ]

    def add_version(self, row: ScheduleVersion) -> None:
        self.session.add(
            ScheduleVersionRow(
                **row.model_dump(exclude={"definition"}),
                definition=row.definition.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def version(self, org: UUID, schedule: UUID, number: int) -> ScheduleVersion | None:
        row = self.session.scalar(
            select(ScheduleVersionRow)
            .where(
                ScheduleVersionRow.organization_id == org,
                ScheduleVersionRow.schedule_id == schedule,
                ScheduleVersionRow.number == number,
            )
            .with_for_update()
        )
        return (
            ScheduleVersion.model_validate(
                {k: getattr(row, k) for k in ScheduleVersion.model_fields}
            )
            if row
            else None
        )

    def versions(self, org: UUID, schedule: UUID, after: UUID | None) -> list[ScheduleVersion]:
        query = select(ScheduleVersionRow).where(
            ScheduleVersionRow.organization_id == org, ScheduleVersionRow.schedule_id == schedule
        )
        if after:
            query = query.where(ScheduleVersionRow.id > after)
        return [
            ScheduleVersion.model_validate(
                {k: getattr(row, k) for k in ScheduleVersion.model_fields}
            )
            for row in self.session.scalars(query.order_by(ScheduleVersionRow.id).limit(101))
        ]

    def save_version(self, row: ScheduleVersion, expected: int) -> bool:
        result = self.session.execute(
            update(ScheduleVersionRow)
            .returning(ScheduleVersionRow.id)
            .where(
                ScheduleVersionRow.organization_id == row.organization_id,
                ScheduleVersionRow.id == row.id,
                ScheduleVersionRow.revision == expected,
            )
            .values(
                **row.model_dump(
                    exclude={
                        "id",
                        "organization_id",
                        "workspace_id",
                        "schedule_id",
                        "number",
                        "definition",
                    }
                ),
                definition=row.definition.model_dump(mode="json"),
            )
        )
        return result.scalar_one_or_none() is not None

    def add_shift(self, row: Shift) -> None:
        self.session.add(
            ShiftRow(
                id=row.id,
                organization_id=row.organization_id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                code=row.code,
                number=row.number,
                snapshot=row.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def shift(self, org: UUID, workspace: UUID, identifier: UUID) -> Shift | None:
        row = self.session.scalar(
            select(ShiftRow).where(
                ShiftRow.organization_id == org,
                ShiftRow.workspace_id == workspace,
                ShiftRow.id == identifier,
            )
        )
        return Shift.model_validate(row.snapshot) if row else None

    def shifts(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Shift]:
        query = select(ShiftRow).where(
            ShiftRow.organization_id == org,
            ShiftRow.workspace_id == workspace,
            ShiftRow.project_id == project,
        )
        if after:
            query = query.where(ShiftRow.id > after)
        return [
            Shift.model_validate(row.snapshot)
            for row in self.session.scalars(query.order_by(ShiftRow.id).limit(101))
        ]

    def add_trigger(self, row: Trigger) -> bool:
        result = self.session.execute(
            insert(TriggerRow)
            .values(**row.model_dump())
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(TriggerRow.id)
        )
        return result.scalar_one_or_none() is not None

    def triggers(
        self,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        code: str,
        start: datetime,
        end: datetime,
    ) -> list[Trigger]:
        rows = self.session.scalars(
            select(TriggerRow)
            .where(
                TriggerRow.organization_id == org,
                TriggerRow.workspace_id == workspace,
                TriggerRow.project_id == project,
                TriggerRow.code == code,
                TriggerRow.occurred_at >= start,
                TriggerRow.occurred_at < end,
            )
            .order_by(TriggerRow.occurred_at)
            .limit(2001)
        )
        return [
            Trigger.model_validate({k: getattr(row, k) for k in Trigger.model_fields})
            for row in rows
        ]
