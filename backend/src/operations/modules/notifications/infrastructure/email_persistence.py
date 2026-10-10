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
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.notifications.application.email_contracts import EmailAttempt, EmailDelivery
from operations.platform.database import Base


class EmailRow(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "recipient_id"],
            ["users.organization_id", "users.id"],
            name="fk_email_deliveries_organization_id_users_recipient",
        ),
        Index(
            "uq_email_invitation_source",
            "organization_id",
            "source_id",
            unique=True,
            postgresql_where=text("source_kind='invitation'"),
        ),
        Index(
            "uq_email_notice_source",
            "organization_id",
            "source_id",
            "recipient_id",
            unique=True,
            postgresql_where=text("source_kind='notice'"),
        ),
        ForeignKeyConstraint(
            ["organization_id", "operator_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint("attempts BETWEEN 0 AND 20", name="attempt_bound"),
        CheckConstraint(
            "state IN ('pending','sending','sent','retry','uncertain','failed','skipped')",
            name="state",
        ),
        CheckConstraint(
            "(source_kind='invitation' AND recipient_id IS NULL) OR "
            "(source_kind='notice' AND recipient_id IS NOT NULL)",
            name="source",
        ),
        Index("ix_email_due", "organization_id", "state", "next_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID]
    recipient_id: Mapped[UUID | None]
    operator_id: Mapped[UUID]
    correlation_id: Mapped[UUID]
    request_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class EmailAttemptRow(Base):
    __tablename__ = "email_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "delivery_id"],
            ["email_deliveries.organization_id", "email_deliveries.id"],
        ),
        UniqueConstraint("organization_id", "delivery_id", "number"),
        CheckConstraint("number BETWEEN 1 AND 20", name="attempt_bound"),
        CheckConstraint(
            "outcome IN ('sent','retry','uncertain','failed','skipped')", name="outcome"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    delivery_id: Mapped[UUID]
    number: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, org: UUID, identifier: UUID) -> EmailDelivery | None:
        row = self.session.scalar(
            select(EmailRow)
            .where(EmailRow.organization_id == org, EmailRow.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (
            EmailDelivery.model_validate(
                {key: getattr(row, key) for key in EmailDelivery.model_fields}
            )
            if row
            else None
        )

    def add(self, delivery: EmailDelivery) -> None:
        self.session.add(EmailRow(**delivery.model_dump()))
        self.session.flush()

    def save(self, delivery: EmailDelivery) -> None:
        self.session.execute(
            update(EmailRow)
            .where(EmailRow.organization_id == delivery.organization_id, EmailRow.id == delivery.id)
            .values(
                state=delivery.state,
                attempts=delivery.attempts,
                next_at=delivery.next_at,
                error_code=delivery.error_code,
            )
        )
        self.session.flush()

    def attempt(self, attempt: EmailAttempt) -> None:
        self.session.add(EmailAttemptRow(**attempt.model_dump()))
        self.session.flush()

    def due(self, org: UUID, now: datetime) -> list[UUID]:
        return list(
            self.session.scalars(
                select(EmailRow.id)
                .where(
                    EmailRow.organization_id == org,
                    EmailRow.state.in_(["pending", "retry", "sending"]),
                    EmailRow.next_at <= now,
                )
                .order_by(EmailRow.next_at, EmailRow.id)
                .limit(100)
            )
        )
