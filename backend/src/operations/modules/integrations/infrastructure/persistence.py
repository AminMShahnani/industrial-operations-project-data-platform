"""Immutable endpoint-version persistence for the integrations module."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
    tuple_,
    update,
)
from sqlalchemy.orm import Mapped, Session, aliased, mapped_column

from operations.contracts import ServiceError
from operations.modules.integrations.application.contracts import EndpointVersion
from operations.modules.integrations.application.delivery_contracts import (
    WebhookAttempt,
    WebhookDeliveryState,
    WebhookDeliveryStatus,
    WebhookIntent,
)
from operations.platform.database import Base


class WebhookEndpointRow(Base):
    __tablename__ = "webhook_endpoint_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        ForeignKeyConstraint(
            ["organization_id", "created_by_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "audit_id"], ["audit_events.organization_id", "audit_events.id"]
        ),
        UniqueConstraint(
            "organization_id", "endpoint_id", "version", name="uq_webhook_endpoint_version"
        ),
        CheckConstraint("version > 0", name="webhook_endpoint_version_positive"),
        CheckConstraint(
            "signing_key_version > 0", name="webhook_endpoint_signing_key_version_positive"
        ),
        CheckConstraint(
            "state IN ('active','revoked') AND ((project_id IS NULL AND workspace_id IS NULL) "
            "OR workspace_id IS NOT NULL)",
            name="webhook_endpoint_scope_state",
        ),
        CheckConstraint(
            "url LIKE 'https://%' AND char_length(name) BETWEEN 1 AND 120 "
            "AND char_length(secret_reference) BETWEEN 1 AND 512",
            name="webhook_endpoint_values",
        ),
        Index(
            "ix_webhook_endpoint_scope_cursor",
            "organization_id",
            "workspace_id",
            "project_id",
            "endpoint_id",
            "version",
        ),
    )
    audit_id: Mapped[UUID] = mapped_column(primary_key=True)
    endpoint_id: Mapped[UUID]
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    version: Mapped[int]
    signing_key_version: Mapped[int]
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    secret_reference: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(10))
    created_by_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookEndpointRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def contract(row: WebhookEndpointRow) -> EndpointVersion:
        return EndpointVersion.model_validate(
            {key: getattr(row, key) for key in EndpointVersion.model_fields}
        )

    def add(self, row: EndpointVersion) -> None:
        self.session.add(WebhookEndpointRow(**row.model_dump()))
        self.session.flush()

    def latest(self, organization_id: UUID, endpoint_id: UUID) -> EndpointVersion | None:
        row = self.session.scalar(
            select(WebhookEndpointRow)
            .where(
                WebhookEndpointRow.organization_id == organization_id,
                WebhookEndpointRow.endpoint_id == endpoint_id,
            )
            .order_by(WebhookEndpointRow.version.desc())
            .limit(1)
        )
        return self.contract(row) if row else None

    def version(
        self, organization_id: UUID, endpoint_id: UUID, number: int
    ) -> EndpointVersion | None:
        row = self.session.scalar(
            select(WebhookEndpointRow).where(
                WebhookEndpointRow.organization_id == organization_id,
                WebhookEndpointRow.endpoint_id == endpoint_id,
                WebhookEndpointRow.version == number,
            )
        )
        return self.contract(row) if row else None

    def page(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        after: UUID | None,
    ) -> list[EndpointVersion]:
        version_row = aliased(WebhookEndpointRow)
        latest_version = (
            select(func.max(version_row.version))
            .where(
                version_row.organization_id == WebhookEndpointRow.organization_id,
                version_row.endpoint_id == WebhookEndpointRow.endpoint_id,
            )
            .correlate(WebhookEndpointRow)
            .scalar_subquery()
        )
        query = select(WebhookEndpointRow).where(
            WebhookEndpointRow.organization_id == organization_id,
            WebhookEndpointRow.workspace_id == workspace_id,
            WebhookEndpointRow.project_id == project_id,
            WebhookEndpointRow.version == latest_version,
        )
        if after:
            query = query.where(WebhookEndpointRow.endpoint_id > after)
        rows = self.session.scalars(query.order_by(WebhookEndpointRow.endpoint_id).limit(101))
        return [self.contract(row) for row in rows]


class WebhookIntentRow(Base):
    __tablename__ = "webhook_delivery_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "event_id"], ["outbox_events.organization_id", "outbox_events.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "run_id"], ["automation_runs.organization_id", "automation_runs.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "rule_version_id"],
            ["automation_versions.organization_id", "automation_versions.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "endpoint_id", "endpoint_version"],
            [
                "webhook_endpoint_versions.organization_id",
                "webhook_endpoint_versions.endpoint_id",
                "webhook_endpoint_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "requested_by_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "run_id", "action_position", name="uq_webhook_intent_action"
        ),
        CheckConstraint(
            "action_position BETWEEN 0 AND 19 AND endpoint_version > 0 "
            "AND workspace_id IS NOT NULL",
            name="webhook_intent_scope_position",
        ),
        Index(
            "ix_webhook_intent_scope_created", "organization_id", "workspace_id", "created_at", "id"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    audit_id: Mapped[UUID] = mapped_column(unique=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    event_id: Mapped[UUID]
    run_id: Mapped[UUID]
    rule_version_id: Mapped[UUID]
    action_position: Mapped[int]
    endpoint_id: Mapped[UUID]
    endpoint_version: Mapped[int]
    requested_by_id: Mapped[UUID]
    correlation_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookIntentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def contract(row: WebhookIntentRow) -> WebhookIntent:
        return WebhookIntent.model_validate(
            {key: getattr(row, key) for key in WebhookIntent.model_fields}
        )

    def get(self, organization_id: UUID, identifier: UUID) -> WebhookIntent | None:
        row = self.session.scalar(
            select(WebhookIntentRow).where(
                WebhookIntentRow.organization_id == organization_id,
                WebhookIntentRow.id == identifier,
            )
        )
        return self.contract(row) if row else None

    def add(self, row: WebhookIntent) -> None:
        self.session.add(WebhookIntentRow(**row.model_dump()))
        self.session.flush()
        self.session.add(
            WebhookDeliveryStateRow(
                id=row.id,
                organization_id=row.organization_id,
                status="pending",
                attempts=0,
                next_at=row.created_at,
                error_code=None,
                updated_at=row.created_at,
                audit_id=row.audit_id,
            )
        )
        self.session.flush()


class WebhookDeliveryStateRow(Base):
    __tablename__ = "webhook_delivery_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "id"],
            ["webhook_delivery_intents.organization_id", "webhook_delivery_intents.id"],
        ),
        ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        CheckConstraint(
            "status IN ('pending','sending','retry','sent','failed','uncertain','skipped') "
            "AND attempts BETWEEN 0 AND 20",
            name="webhook_delivery_status_attempts",
        ),
        Index("ix_webhook_delivery_due", "status", "next_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    audit_id: Mapped[UUID]


class WebhookAttemptRow(Base):
    __tablename__ = "webhook_delivery_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "delivery_id"],
            ["webhook_delivery_states.organization_id", "webhook_delivery_states.id"],
        ),
        ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        UniqueConstraint("organization_id", "delivery_id", "number"),
        CheckConstraint(
            "number BETWEEN 1 AND 20 AND outcome IN "
            "('sent','retry','failed','uncertain','skipped')",
            name="webhook_attempt_values",
        ),
        Index("ix_webhook_attempt_cursor", "organization_id", "delivery_id", "number"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    delivery_id: Mapped[UUID]
    number: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    audit_id: Mapped[UUID] = mapped_column(unique=True)


class WebhookDeliveryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def intent(self, organization_id: UUID, identifier: UUID) -> WebhookIntent | None:
        return WebhookIntentRepository(self.session).get(organization_id, identifier)

    def state(
        self, organization_id: UUID, identifier: UUID, lock: bool = False
    ) -> WebhookDeliveryState | None:
        query = select(WebhookDeliveryStateRow).where(
            WebhookDeliveryStateRow.organization_id == organization_id,
            WebhookDeliveryStateRow.id == identifier,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        if row is None:
            return None
        return WebhookDeliveryState.model_validate(
            {key: getattr(row, key) for key in WebhookDeliveryState.model_fields}
        )

    def due(self, now: datetime, limit: int = 100) -> list[WebhookDeliveryState]:
        rows = self.session.scalars(
            select(WebhookDeliveryStateRow)
            .where(
                WebhookDeliveryStateRow.status.in_(["pending", "retry", "sending"]),
                WebhookDeliveryStateRow.next_at <= now,
            )
            .order_by(WebhookDeliveryStateRow.next_at, WebhookDeliveryStateRow.id)
            .limit(min(max(limit, 1), 100))
        )
        return [
            WebhookDeliveryState.model_validate(
                {key: getattr(row, key) for key in WebhookDeliveryState.model_fields}
            )
            for row in rows
        ]

    def page(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        state: WebhookDeliveryStatus | None,
        cursor: UUID | None,
        limit: int = 101,
    ) -> list[tuple[WebhookIntent, WebhookDeliveryState]]:
        query = (
            select(WebhookIntentRow, WebhookDeliveryStateRow)
            .join(
                WebhookDeliveryStateRow,
                (WebhookDeliveryStateRow.organization_id == WebhookIntentRow.organization_id)
                & (WebhookDeliveryStateRow.id == WebhookIntentRow.id),
            )
            .where(WebhookIntentRow.organization_id == organization_id)
        )
        if workspace_id is not None:
            query = query.where(WebhookIntentRow.workspace_id == workspace_id)
        if project_id is not None:
            query = query.where(WebhookIntentRow.project_id == project_id)
        if state is not None:
            query = query.where(WebhookDeliveryStateRow.status == state)
        if cursor is not None:
            boundary = self.session.scalar(
                select(WebhookIntentRow).where(
                    WebhookIntentRow.organization_id == organization_id,
                    WebhookIntentRow.id == cursor,
                )
            )
            if boundary is None or (
                workspace_id is not None and boundary.workspace_id != workspace_id
            ):
                raise ServiceError(422, "webhook_delivery_cursor_invalid")
            if project_id is not None and boundary.project_id != project_id:
                raise ServiceError(422, "webhook_delivery_cursor_invalid")
            if state is not None:
                boundary_state = self.session.get(
                    WebhookDeliveryStateRow, (boundary.id, organization_id)
                )
                if boundary_state is None or boundary_state.status != state:
                    raise ServiceError(422, "webhook_delivery_cursor_invalid")
            query = query.where(
                tuple_(WebhookIntentRow.created_at, WebhookIntentRow.id)
                > (boundary.created_at, boundary.id)
            )
        rows = self.session.execute(
            query.order_by(WebhookIntentRow.created_at, WebhookIntentRow.id).limit(
                min(max(limit, 1), 101)
            )
        )
        return [
            (
                WebhookIntent.model_validate(
                    {key: getattr(intent, key) for key in WebhookIntent.model_fields}
                ),
                WebhookDeliveryState.model_validate(
                    {key: getattr(delivery, key) for key in WebhookDeliveryState.model_fields}
                ),
            )
            for intent, delivery in rows
        ]

    def attempts(self, organization_id: UUID, identifier: UUID) -> list[WebhookAttempt]:
        return [
            WebhookAttempt.model_validate(
                {key: getattr(row, key) for key in WebhookAttempt.model_fields}
            )
            for row in self.session.scalars(
                select(WebhookAttemptRow)
                .where(
                    WebhookAttemptRow.organization_id == organization_id,
                    WebhookAttemptRow.delivery_id == identifier,
                )
                .order_by(WebhookAttemptRow.number)
                .limit(20)
            )
        ]

    def save_state(self, row: WebhookDeliveryState) -> None:
        self.session.execute(
            update(WebhookDeliveryStateRow)
            .where(
                WebhookDeliveryStateRow.organization_id == row.organization_id,
                WebhookDeliveryStateRow.id == row.id,
            )
            .values(**row.model_dump(exclude={"id", "organization_id"}))
        )
        self.session.flush()

    def add_attempt(self, row: WebhookAttempt) -> None:
        self.session.add(WebhookAttemptRow(**row.model_dump()))
        self.session.flush()
