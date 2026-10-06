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
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.automation.application.contracts import (
    Receipt,
    Rule,
    RuleVersion,
    Run,
    RunAttempt,
)
from operations.modules.automation.application.events import Delivery, OperationalEvent
from operations.platform.database import Base


class EventRow(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["users.organization_id", "users.id"]
        ),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(
            "project_id IS NULL OR workspace_id IS NOT NULL", name="outbox_project_scope"
        ),
        Index("ix_outbox_scope_cursor", "organization_id", "workspace_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    actor_id: Mapped[UUID | None]
    type: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    envelope: Mapped[dict[str, object]] = mapped_column(JSONB)


class DeliveryRow(Base):
    __tablename__ = "outbox_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["outbox_events.organization_id", "outbox_events.id"]
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "event_id", "consumer", name="uq_delivery_consumer"),
        CheckConstraint(
            "consumer IN ('automation','notifications') AND "
            "state IN ('pending','dispatched','completed','retry','dead_letter') "
            "AND attempts BETWEEN 0 AND 20",
            name="delivery_state",
        ),
        Index("ix_delivery_due", "organization_id", "state", "next_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    event_id: Mapped[UUID]
    consumer: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class RuleRow(Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("organization_id", "workspace_id", "id"),
        Index("ix_automation_rule_scope", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(120))
    active_number: Mapped[int | None]
    revision: Mapped[int]


class VersionRow(Base):
    __tablename__ = "automation_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "rule_id"],
            [
                "automation_rules.organization_id",
                "automation_rules.workspace_id",
                "automation_rules.id",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "activator_id"], ["users.organization_id", "users.id"]
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "workspace_id", "rule_id", "number", name="uq_rule_version_number"
        ),
        CheckConstraint(
            "number>0 AND revision>0 AND ((state='draft' AND activator_id IS NULL "
            "AND activated_at IS NULL AND content_sha256 IS NULL) OR "
            "(state IN ('active','retired') AND activator_id IS NOT NULL "
            "AND activated_at IS NOT NULL AND length(content_sha256)=64))",
            name="automation_version_state",
        ),
        Index(
            "uq_automation_active_rule",
            "organization_id",
            "rule_id",
            unique=True,
            postgresql_where=text("state='active'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    rule_id: Mapped[UUID]
    number: Mapped[int]
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    revision: Mapped[int]
    state: Mapped[str] = mapped_column(String(20))
    activator_id: Mapped[UUID | None]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class RunRow(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "rule_version_id"],
            ["automation_versions.organization_id", "automation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["outbox_events.organization_id", "outbox_events.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "delegator_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "rule_version_id", "event_id", name="uq_run_event_version"
        ),
        CheckConstraint(
            "state IN ('pending','completed','skipped','retry','dead_letter') "
            "AND attempts BETWEEN 0 AND 20",
            name="automation_run_state",
        ),
        Index("ix_automation_run_scope", "organization_id", "workspace_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    rule_version_id: Mapped[UUID]
    event_id: Mapped[UUID]
    delegator_id: Mapped[UUID]
    trigger_actor_id: Mapped[UUID | None]
    correlation_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))


class AttemptRow(Base):
    __tablename__ = "automation_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["automation_runs.organization_id", "automation_runs.id"]
        ),
        UniqueConstraint("organization_id", "run_id", "number"),
        CheckConstraint(
            "number BETWEEN 1 AND 20 AND finished_at>=started_at AND "
            "outcome IN ('completed','skipped','retry','dead_letter')",
            name="attempt_evidence",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    run_id: Mapped[UUID]
    number: Mapped[int]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(100))


class ReceiptRow(Base):
    __tablename__ = "automation_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["automation_runs.organization_id", "automation_runs.id"]
        ),
        UniqueConstraint("organization_id", "run_id", "position"),
        CheckConstraint("position BETWEEN 0 AND 19", name="automation_receipt_position"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    run_id: Mapped[UUID]
    position: Mapped[int]
    kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def matching(self, event: OperationalEvent) -> list[RuleVersion]:
        rows = self.session.scalars(
            select(VersionRow)
            .join(RuleRow, RuleRow.id == VersionRow.rule_id)
            .where(
                VersionRow.organization_id == event.organization_id,
                VersionRow.workspace_id == event.workspace_id,
                RuleRow.project_id == event.project_id,
                VersionRow.state == "active",
                VersionRow.definition["trigger"].astext == event.type,
            )
            .order_by(VersionRow.id)
            .limit(1001)
            .with_for_update(read=True, of=VersionRow)
        )
        return [
            RuleVersion.model_validate({key: getattr(row, key) for key in RuleVersion.model_fields})
            for row in rows
        ]

    def add_delivery(self, row: Delivery) -> None:
        self.session.add(DeliveryRow(**row.model_dump()))
        self.session.flush()

    def delivery(self, org: UUID, identifier: UUID, lock: bool = False) -> Delivery | None:
        query = select(DeliveryRow).where(
            DeliveryRow.organization_id == org, DeliveryRow.id == identifier
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return (
            Delivery.model_validate({key: getattr(row, key) for key in Delivery.model_fields})
            if row
            else None
        )

    def due_deliveries(self, org: UUID, now: datetime) -> list[Delivery]:
        rows = self.session.scalars(
            select(DeliveryRow)
            .where(
                DeliveryRow.organization_id == org,
                DeliveryRow.state.in_(["pending", "retry", "dispatched"]),
                DeliveryRow.next_at <= now,
            )
            .order_by(DeliveryRow.next_at, DeliveryRow.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        return [
            Delivery.model_validate({key: getattr(row, key) for key in Delivery.model_fields})
            for row in rows
        ]

    def save_delivery(self, row: Delivery) -> None:
        self.session.execute(
            update(DeliveryRow)
            .where(DeliveryRow.organization_id == row.organization_id, DeliveryRow.id == row.id)
            .values(
                state=row.state,
                attempts=row.attempts,
                next_at=row.next_at,
                error_code=row.error_code,
            )
        )
        self.session.flush()

    def add_run(self, row: Run) -> None:
        self.session.add(RunRow(**row.model_dump()))
        self.session.flush()

    def run(self, org: UUID, identifier: UUID, lock: bool = False) -> Run | None:
        query = select(RunRow).where(RunRow.organization_id == org, RunRow.id == identifier)
        row = self.session.scalar(query.with_for_update() if lock else query)
        return (
            Run.model_validate({key: getattr(row, key) for key in Run.model_fields})
            if row
            else None
        )

    def event_runs(self, org: UUID, event: UUID) -> list[Run]:
        rows = self.session.scalars(
            select(RunRow)
            .where(RunRow.organization_id == org, RunRow.event_id == event)
            .order_by(RunRow.id)
            .limit(1001)
        )
        return [
            Run.model_validate({key: getattr(row, key) for key in Run.model_fields}) for row in rows
        ]

    def runs(
        self, org: UUID, workspace: UUID, version: UUID | None, after: UUID | None
    ) -> list[Run]:
        query = select(RunRow).where(
            RunRow.organization_id == org, RunRow.workspace_id == workspace
        )
        if version:
            query = query.where(RunRow.rule_version_id == version)
        if after:
            query = query.where(RunRow.id > after)
        return [
            Run.model_validate({key: getattr(row, key) for key in Run.model_fields})
            for row in self.session.scalars(query.order_by(RunRow.id).limit(101))
        ]

    def save_run(self, row: Run) -> None:
        self.session.execute(
            update(RunRow)
            .where(RunRow.organization_id == row.organization_id, RunRow.id == row.id)
            .values(
                state=row.state,
                attempts=row.attempts,
                next_at=row.next_at,
                completed_at=row.completed_at,
                error_code=row.error_code,
            )
        )
        self.session.flush()

    def add_attempt(self, row: RunAttempt) -> None:
        self.session.add(AttemptRow(**row.model_dump()))
        self.session.flush()

    def attempts(self, org: UUID, run: UUID) -> list[RunAttempt]:
        return [
            RunAttempt.model_validate({key: getattr(row, key) for key in RunAttempt.model_fields})
            for row in self.session.scalars(
                select(AttemptRow)
                .where(AttemptRow.organization_id == org, AttemptRow.run_id == run)
                .order_by(AttemptRow.number)
                .limit(100)
            )
        ]

    def add_receipt(self, row: Receipt) -> None:
        self.session.add(ReceiptRow(**row.model_dump()))
        self.session.flush()

    def receipts(self, org: UUID, run: UUID) -> list[Receipt]:
        return [
            Receipt.model_validate({key: getattr(row, key) for key in Receipt.model_fields})
            for row in self.session.scalars(
                select(ReceiptRow)
                .where(ReceiptRow.organization_id == org, ReceiptRow.run_id == run)
                .order_by(ReceiptRow.position)
                .limit(20)
            )
        ]

    def append(self, event: OperationalEvent) -> None:
        self.session.add(
            EventRow(
                id=event.id,
                organization_id=event.organization_id,
                workspace_id=event.workspace_id,
                project_id=event.project_id,
                actor_id=event.actor_id,
                type=event.type,
                occurred_at=event.occurred_at,
                envelope=event.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def event(self, org: UUID, identifier: UUID) -> OperationalEvent | None:
        row = self.session.scalar(
            select(EventRow).where(EventRow.organization_id == org, EventRow.id == identifier)
        )
        return OperationalEvent.model_validate(row.envelope) if row else None

    def create_rule(self, row: Rule) -> None:
        self.session.add(RuleRow(**row.model_dump()))
        self.session.flush()

    def rule(self, org: UUID, workspace: UUID, identifier: UUID, lock: bool = False) -> Rule | None:
        query = select(RuleRow).where(
            RuleRow.organization_id == org,
            RuleRow.workspace_id == workspace,
            RuleRow.id == identifier,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return (
            Rule.model_validate({key: getattr(row, key) for key in Rule.model_fields})
            if row
            else None
        )

    def rules(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Rule]:
        query = select(RuleRow).where(
            RuleRow.organization_id == org,
            RuleRow.workspace_id == workspace,
            RuleRow.project_id == project,
        )
        if after:
            query = query.where(RuleRow.id > after)
        return [
            Rule.model_validate({key: getattr(row, key) for key in Rule.model_fields})
            for row in self.session.scalars(query.order_by(RuleRow.id).limit(101))
        ]

    def save_rule(self, row: Rule, expected: int) -> bool:
        result = self.session.scalar(
            update(RuleRow)
            .where(
                RuleRow.organization_id == row.organization_id,
                RuleRow.id == row.id,
                RuleRow.revision == expected,
            )
            .values(name=row.name, active_number=row.active_number, revision=row.revision)
            .returning(RuleRow.id)
        )
        return result is not None

    def add_version(self, row: RuleVersion) -> None:
        self.session.add(
            VersionRow(
                **row.model_dump(exclude={"definition"}),
                definition=row.definition.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def version(
        self, org: UUID, workspace: UUID, rule: UUID, number: int, lock: bool = False
    ) -> RuleVersion | None:
        query = select(VersionRow).where(
            VersionRow.organization_id == org,
            VersionRow.workspace_id == workspace,
            VersionRow.rule_id == rule,
            VersionRow.number == number,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return (
            RuleVersion.model_validate({key: getattr(row, key) for key in RuleVersion.model_fields})
            if row
            else None
        )

    def version_by_id(self, org: UUID, identifier: UUID) -> RuleVersion | None:
        row = self.session.scalar(
            select(VersionRow).where(VersionRow.organization_id == org, VersionRow.id == identifier)
        )
        return (
            RuleVersion.model_validate({key: getattr(row, key) for key in RuleVersion.model_fields})
            if row
            else None
        )

    def versions(
        self, org: UUID, workspace: UUID, rule: UUID, after: UUID | None
    ) -> list[RuleVersion]:
        query = select(VersionRow).where(
            VersionRow.organization_id == org,
            VersionRow.workspace_id == workspace,
            VersionRow.rule_id == rule,
        )
        if after:
            query = query.where(VersionRow.id > after)
        return [
            RuleVersion.model_validate({key: getattr(row, key) for key in RuleVersion.model_fields})
            for row in self.session.scalars(query.order_by(VersionRow.id).limit(101))
        ]

    def save_version(self, row: RuleVersion, expected: int) -> bool:
        result = self.session.scalar(
            update(VersionRow)
            .where(
                VersionRow.organization_id == row.organization_id,
                VersionRow.id == row.id,
                VersionRow.revision == expected,
            )
            .values(
                **row.model_dump(
                    exclude={
                        "id",
                        "organization_id",
                        "workspace_id",
                        "rule_id",
                        "number",
                        "definition",
                    }
                ),
                definition=row.definition.model_dump(mode="json"),
            )
            .returning(VersionRow.id)
        )
        return result is not None
