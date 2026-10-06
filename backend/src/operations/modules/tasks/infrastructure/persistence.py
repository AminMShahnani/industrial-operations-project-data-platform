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

from operations.modules.tasks.application.contracts import Reminder, Task
from operations.platform.database import Base


class TaskRow(Base):
    __tablename__ = "task_occurrences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            [
                "organization_id",
                "workspace_id",
                "schedule_id",
                "schedule_version_id",
                "schedule_number",
            ],
            [
                "schedule_versions.organization_id",
                "schedule_versions.workspace_id",
                "schedule_versions.schedule_id",
                "schedule_versions.id",
                "schedule_versions.number",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_id", "form_version_id", "form_number"],
            [
                "form_versions.organization_id",
                "form_versions.workspace_id",
                "form_versions.form_id",
                "form_versions.id",
                "form_versions.number",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "claimant_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "submission_id", "claimant_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
        ),
        UniqueConstraint("organization_id", "workspace_id", "id", name="uq_task_scope"),
        UniqueConstraint(
            "organization_id",
            "schedule_version_id",
            "occurs_at",
            "assignment_key",
            name="uq_task_materialization",
        ),
        UniqueConstraint("organization_id", "submission_id", name="uq_task_submission"),
        CheckConstraint(
            "revision > 0 AND due_at >= occurs_at AND state IN ('open','in_progress',"
            "'submitted','awaiting_review','returned','approved','cancelled','superseded')",
            name="task_state",
        ),
        CheckConstraint(
            "(state IN ('open','superseded') AND claimant_id IS NULL AND submission_id IS NULL) "
            "OR state='cancelled' OR (state IN ('in_progress','submitted','awaiting_review',"
            "'returned','approved') AND claimant_id IS NOT NULL AND submission_id IS NOT NULL)",
            name="task_claim",
        ),
        Index(
            "ix_tasks_scope_state_due_cursor",
            "organization_id",
            "workspace_id",
            "project_id",
            "state",
            "due_at",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    schedule_id: Mapped[UUID]
    schedule_version_id: Mapped[UUID]
    schedule_number: Mapped[int]
    form_id: Mapped[UUID]
    form_version_id: Mapped[UUID]
    form_number: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80))
    occurs_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assignment: Mapped[dict[str, object]] = mapped_column(JSONB)
    assignment_key: Mapped[str] = mapped_column(String(100))
    recipient_ids: Mapped[list[str]] = mapped_column(JSONB)
    reminder_offsets: Mapped[list[int]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    claimant_id: Mapped[UUID | None]
    submission_id: Mapped[UUID | None]
    revision: Mapped[int]


class RecipientRow(Base):
    __tablename__ = "task_recipients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "task_id"],
            [
                "task_occurrences.organization_id",
                "task_occurrences.workspace_id",
                "task_occurrences.id",
            ],
        ),
        ForeignKeyConstraint(["organization_id", "user_id"], ["users.organization_id", "users.id"]),
        Index(
            "ix_task_recipients_personal", "organization_id", "workspace_id", "user_id", "task_id"
        ),
    )
    task_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]


class ReminderRow(Base):
    __tablename__ = "task_reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "task_id"],
            [
                "task_occurrences.organization_id",
                "task_occurrences.workspace_id",
                "task_occurrences.id",
            ],
        ),
        UniqueConstraint(
            "organization_id", "task_id", "offset_seconds", name="uq_task_reminder_once"
        ),
        Index("ix_task_reminders_scope_cursor", "organization_id", "workspace_id", "task_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    task_id: Mapped[UUID]
    offset_seconds: Mapped[int]
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def task_contract(row: TaskRow) -> Task:
    return Task.model_validate({k: getattr(row, k) for k in Task.model_fields})


class TaskRepository:
    def by_submission(self, org: UUID, workspace: UUID, submission: UUID) -> Task | None:
        row = self.session.scalar(
            select(TaskRow)
            .where(
                TaskRow.organization_id == org,
                TaskRow.workspace_id == workspace,
                TaskRow.submission_id == submission,
            )
            .with_for_update()
        )
        return task_contract(row) if row else None

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, row: Task) -> bool:
        values = row.model_dump(exclude={"assignment", "recipient_ids"})
        values.update(
            assignment=row.assignment.model_dump(mode="json"),
            recipient_ids=[str(x) for x in row.recipient_ids],
        )
        result = self.session.execute(
            insert(TaskRow)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_task_materialization")
            .returning(TaskRow.id)
        )
        if result.scalar_one_or_none() is None:
            return False
        self.session.add_all(
            [
                RecipientRow(
                    task_id=row.id,
                    user_id=user,
                    organization_id=row.organization_id,
                    workspace_id=row.workspace_id,
                )
                for user in row.recipient_ids
            ]
        )
        self.session.flush()
        return True

    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Task | None:
        row = self.session.scalar(
            select(TaskRow)
            .where(
                TaskRow.organization_id == org,
                TaskRow.workspace_id == workspace,
                TaskRow.id == identifier,
            )
            .with_for_update()
        )
        return task_contract(row) if row else None

    def save(self, row: Task, expected: int) -> bool:
        result = self.session.execute(
            update(TaskRow)
            .returning(TaskRow.id)
            .where(
                TaskRow.organization_id == row.organization_id,
                TaskRow.id == row.id,
                TaskRow.revision == expected,
            )
            .values(
                state=row.state,
                claimant_id=row.claimant_id,
                submission_id=row.submission_id,
                revision=row.revision,
            )
        )
        return result.scalar_one_or_none() is not None

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
    ) -> list[Task]:
        query = select(TaskRow).where(
            TaskRow.organization_id == org,
            TaskRow.workspace_id == workspace,
            TaskRow.project_id == project,
        )
        if user:
            query = query.join(RecipientRow, RecipientRow.task_id == TaskRow.id).where(
                RecipientRow.user_id == user
            )
        if assignment:
            query = query.where(TaskRow.assignment_key == assignment)
        if view == "overdue":
            query = query.where(
                TaskRow.due_at < start, TaskRow.state.in_(["open", "in_progress", "returned"])
            )
        elif view == "due_today":
            query = query.where(
                TaskRow.due_at >= start,
                TaskRow.due_at < end,
                TaskRow.state.in_(["open", "in_progress", "returned"]),
            )
        elif view == "upcoming":
            query = query.where(TaskRow.occurs_at >= end, TaskRow.state == "open")
        elif view in {"returned", "awaiting_review"}:
            query = query.where(TaskRow.state == view)
        if after:
            query = query.where(TaskRow.id > after)
        return [
            task_contract(row)
            for row in self.session.scalars(query.order_by(TaskRow.id).limit(101))
        ]

    def future_open(
        self, org: UUID, workspace: UUID, schedule: UUID, before_number: int, now: datetime
    ) -> list[Task]:
        return [
            task_contract(row)
            for row in self.session.scalars(
                select(TaskRow)
                .where(
                    TaskRow.organization_id == org,
                    TaskRow.workspace_id == workspace,
                    TaskRow.schedule_id == schedule,
                    TaskRow.schedule_number < before_number,
                    TaskRow.occurs_at >= now,
                    TaskRow.state == "open",
                )
                .order_by(TaskRow.id)
                .limit(2001)
                .with_for_update()
            )
        ]

    def reminder_candidates(
        self, org: UUID, workspace: UUID, project: UUID | None, now: datetime, after: UUID | None
    ) -> list[Task]:
        query = select(TaskRow).where(
            TaskRow.organization_id == org,
            TaskRow.workspace_id == workspace,
            TaskRow.project_id == project,
            TaskRow.state.in_(["open", "in_progress", "returned"]),
            TaskRow.due_at <= now.replace(microsecond=0),
        )
        if after:
            query = query.where(TaskRow.id > after)
        return [
            task_contract(row)
            for row in self.session.scalars(query.order_by(TaskRow.id).limit(101))
        ]

    def add_reminder(self, row: Reminder) -> bool:
        result = self.session.execute(
            insert(ReminderRow)
            .values(**row.model_dump())
            .on_conflict_do_nothing(constraint="uq_task_reminder_once")
            .returning(ReminderRow.id)
        )
        return result.scalar_one_or_none() is not None

    def reminders(
        self, org: UUID, workspace: UUID, task: UUID, after: UUID | None
    ) -> list[Reminder]:
        query = select(ReminderRow).where(
            ReminderRow.organization_id == org,
            ReminderRow.workspace_id == workspace,
            ReminderRow.task_id == task,
        )
        if after:
            query = query.where(ReminderRow.id > after)
        return [
            Reminder.model_validate({k: getattr(row, k) for k in Reminder.model_fields})
            for row in self.session.scalars(query.order_by(ReminderRow.id).limit(101))
        ]
