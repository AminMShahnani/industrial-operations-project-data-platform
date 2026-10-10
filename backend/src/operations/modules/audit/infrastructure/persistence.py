from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.audit.application.contracts import AuditEvent
from operations.modules.identity.application.contracts import Principal
from operations.platform.database import Base


class AuditRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_time", "organization_id", "occurred_at", "id"),
        UniqueConstraint("organization_id", "id", name="uq_audit_tenant_identity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    organization_id: Mapped[UUID | None]
    actor_id: Mapped[UUID | None]
    actor_issuer: Mapped[str | None] = mapped_column(String(500))
    actor_subject: Mapped[str | None] = mapped_column(String(255))
    correlation_id: Mapped[UUID]
    request_id: Mapped[UUID]
    aggregate_type: Mapped[str] = mapped_column(String(60))
    aggregate_id: Mapped[UUID | None]
    payload_version: Mapped[int]
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class AuditRepository:
    def __init__(self, session: Session, principal: Principal | None = None) -> None:
        self.session, self.principal = session, principal

    def append(self, event: AuditEvent) -> None:
        values = event.model_dump(exclude={"payload"})
        if self.principal:
            values.update(actor_issuer=self.principal.issuer, actor_subject=self.principal.subject)
        self.session.add(AuditRow(**values, payload=event.payload.model_dump(mode="json")))
        self.session.flush()

    def get(self, org: UUID, identifier: UUID) -> AuditEvent | None:
        row = self.session.scalar(
            select(AuditRow).where(AuditRow.organization_id == org, AuditRow.id == identifier)
        )
        return (
            AuditEvent.model_validate(
                {name: getattr(row, name) for name in AuditEvent.model_fields}
            )
            if row
            else None
        )
