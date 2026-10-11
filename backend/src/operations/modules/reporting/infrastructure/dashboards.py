"""Creator-private, audited dashboard definition persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.reporting.application.contracts import Dashboard, DashboardDefinition
from operations.platform.database import Base


class DashboardVersionRow(Base):
    __tablename__ = "dashboard_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "audit_id"], ["audit_events.organization_id", "audit_events.id"]
        ),
        UniqueConstraint("organization_id", "dashboard_id", "version", name="uq_dashboard_version"),
        UniqueConstraint("organization_id", "dashboard_id", "audit_id", name="uq_dashboard_audit"),
        Index(
            "ix_dashboard_owner_scope",
            "organization_id",
            "workspace_id",
            "owner_id",
            "dashboard_id",
            "version",
        ),
    )
    audit_id: Mapped[UUID] = mapped_column(primary_key=True)
    dashboard_id: Mapped[UUID]
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DashboardStateRow(Base):
    __tablename__ = "dashboard_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "audit_id"], ["audit_events.organization_id", "audit_events.id"]
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(primary_key=True)
    dashboard_id: Mapped[UUID] = mapped_column(primary_key=True)
    audit_id: Mapped[UUID]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool]


class DashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _contract(version: DashboardVersionRow, state: DashboardStateRow) -> Dashboard:
        return Dashboard(
            id=version.dashboard_id,
            organization_id=version.organization_id,
            workspace_id=version.workspace_id,
            owner_id=version.owner_id,
            name=version.name,
            definition=DashboardDefinition.model_validate(version.definition),
            version=version.version,
            definition_sha256=version.definition_sha256,
            created_at=version.created_at,
            updated_at=state.updated_at,
            archived=state.archived,
            audit_id=version.audit_id,
        )

    def _latest(
        self, org: UUID, dashboard_id: UUID
    ) -> tuple[DashboardVersionRow, DashboardStateRow] | None:
        latest = (
            select(func.max(DashboardVersionRow.version))
            .where(
                DashboardVersionRow.organization_id == org,
                DashboardVersionRow.dashboard_id == dashboard_id,
            )
            .scalar_subquery()
        )
        row = self.session.execute(
            select(DashboardVersionRow, DashboardStateRow)
            .join(
                DashboardStateRow,
                (DashboardStateRow.organization_id == DashboardVersionRow.organization_id)
                & (DashboardStateRow.dashboard_id == DashboardVersionRow.dashboard_id),
            )
            .where(
                DashboardVersionRow.organization_id == org,
                DashboardVersionRow.dashboard_id == dashboard_id,
                DashboardVersionRow.version == latest,
            )
        ).first()
        return (row[0], row[1]) if row else None

    def create(self, dashboard: Dashboard) -> None:
        self.session.add(
            DashboardVersionRow(
                audit_id=dashboard.audit_id,
                dashboard_id=dashboard.id,
                organization_id=dashboard.organization_id,
                workspace_id=dashboard.workspace_id,
                owner_id=dashboard.owner_id,
                name=dashboard.name,
                definition=dashboard.definition.model_dump(mode="json"),
                version=dashboard.version,
                definition_sha256=dashboard.definition_sha256,
                created_at=dashboard.created_at,
            )
        )
        self.session.flush()
        self.session.add(
            DashboardStateRow(
                organization_id=dashboard.organization_id,
                dashboard_id=dashboard.id,
                audit_id=dashboard.audit_id,
                updated_at=dashboard.updated_at,
                archived=False,
            )
        )
        self.session.flush()

    def get(self, organization_id: UUID, dashboard_id: UUID) -> Dashboard | None:
        latest = self._latest(organization_id, dashboard_id)
        return self._contract(*latest) if latest else None

    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID, cursor: UUID | None
    ) -> list[Dashboard]:
        latest = (
            select(
                DashboardVersionRow.organization_id.label("organization_id"),
                DashboardVersionRow.dashboard_id.label("dashboard_id"),
                func.max(DashboardVersionRow.version).label("version"),
            )
            .where(
                DashboardVersionRow.organization_id == organization_id,
                DashboardVersionRow.workspace_id == workspace_id,
                DashboardVersionRow.owner_id == owner_id,
            )
            .group_by(DashboardVersionRow.organization_id, DashboardVersionRow.dashboard_id)
            .subquery()
        )
        query = (
            select(DashboardVersionRow, DashboardStateRow)
            .join(
                DashboardStateRow,
                (DashboardStateRow.organization_id == DashboardVersionRow.organization_id)
                & (DashboardStateRow.dashboard_id == DashboardVersionRow.dashboard_id),
            )
            .where(
                DashboardVersionRow.organization_id == organization_id,
                DashboardVersionRow.workspace_id == workspace_id,
                DashboardVersionRow.owner_id == owner_id,
                DashboardVersionRow.dashboard_id == latest.c.dashboard_id,
                DashboardVersionRow.version == latest.c.version,
                DashboardStateRow.archived.is_(False),
            )
            .order_by(DashboardVersionRow.dashboard_id)
            .limit(101)
        )
        if cursor is not None:
            query = query.where(DashboardVersionRow.dashboard_id > cursor)
        return [self._contract(version, state) for version, state in self.session.execute(query)]

    def append(self, dashboard: Dashboard, expected_version: int) -> bool:
        state = self.session.scalar(
            select(DashboardStateRow)
            .where(
                DashboardStateRow.organization_id == dashboard.organization_id,
                DashboardStateRow.dashboard_id == dashboard.id,
                DashboardStateRow.archived.is_(False),
            )
            .with_for_update()
        )
        current = self.get(dashboard.organization_id, dashboard.id)
        if state is None or current is None or current.version != expected_version:
            return False
        self.session.add(
            DashboardVersionRow(
                audit_id=dashboard.audit_id,
                dashboard_id=dashboard.id,
                organization_id=dashboard.organization_id,
                workspace_id=dashboard.workspace_id,
                owner_id=dashboard.owner_id,
                name=dashboard.name,
                definition=dashboard.definition.model_dump(mode="json"),
                version=dashboard.version,
                definition_sha256=dashboard.definition_sha256,
                created_at=dashboard.created_at,
            )
        )
        self.session.flush()
        result = self.session.execute(
            update(DashboardStateRow)
            .where(
                DashboardStateRow.organization_id == dashboard.organization_id,
                DashboardStateRow.dashboard_id == dashboard.id,
                DashboardStateRow.archived.is_(False),
            )
            .values(audit_id=dashboard.audit_id, updated_at=dashboard.updated_at)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    def archive(
        self,
        organization_id: UUID,
        dashboard_id: UUID,
        owner_id: UUID,
        expected: int,
        updated_at: datetime,
        audit_id: UUID,
    ) -> bool:
        current = self.get(organization_id, dashboard_id)
        if current is None or current.owner_id != owner_id or current.version != expected:
            return False
        result = self.session.execute(
            update(DashboardStateRow)
            .where(
                DashboardStateRow.organization_id == organization_id,
                DashboardStateRow.dashboard_id == dashboard_id,
                DashboardStateRow.audit_id == current.audit_id,
                DashboardStateRow.archived.is_(False),
            )
            .values(audit_id=audit_id, updated_at=updated_at, archived=True)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1
