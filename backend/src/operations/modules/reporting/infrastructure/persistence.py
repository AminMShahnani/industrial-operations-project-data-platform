"""Audited, immutable saved report definitions."""

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

from operations.modules.reporting.application.contracts import SavedReport, SavedReportDefinition
from operations.platform.database import Base


class SavedReportVersionRow(Base):
    __tablename__ = "saved_report_versions"
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
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("organization_id", "report_id", "version", name="uq_saved_report_version"),
        UniqueConstraint("organization_id", "report_id", "audit_id", name="uq_saved_report_audit"),
        Index(
            "ix_saved_report_owner_scope",
            "organization_id",
            "workspace_id",
            "owner_id",
            "report_id",
            "version",
            unique=False,
        ),
    )
    audit_id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID]
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedReportIdentityRow(Base):
    __tablename__ = "saved_report_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "audit_id"], ["audit_events.organization_id", "audit_events.id"]
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    audit_id: Mapped[UUID]


class SavedReportStateRow(Base):
    __tablename__ = "saved_report_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "report_id"],
            ["saved_report_identities.organization_id", "saved_report_identities.report_id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "audit_id"], ["audit_events.organization_id", "audit_events.id"]
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID] = mapped_column(primary_key=True)
    audit_id: Mapped[UUID]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool]


class SavedReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _contract(version: SavedReportVersionRow, state: SavedReportStateRow) -> SavedReport:
        return SavedReport(
            id=version.report_id,
            organization_id=version.organization_id,
            workspace_id=version.workspace_id,
            project_id=version.project_id,
            owner_id=version.owner_id,
            name=version.name,
            definition=SavedReportDefinition.model_validate(version.definition),
            version=version.version,
            definition_sha256=version.definition_sha256,
            created_at=version.created_at,
            updated_at=state.updated_at,
            archived=state.archived,
            audit_id=version.audit_id,
        )

    def _latest(
        self, organization_id: UUID, report_id: UUID
    ) -> tuple[SavedReportVersionRow, SavedReportStateRow] | None:
        latest = (
            select(func.max(SavedReportVersionRow.version))
            .where(
                SavedReportVersionRow.organization_id == organization_id,
                SavedReportVersionRow.report_id == report_id,
            )
            .scalar_subquery()
        )
        row = self.session.execute(
            select(SavedReportVersionRow, SavedReportStateRow)
            .join(
                SavedReportStateRow,
                (SavedReportStateRow.organization_id == SavedReportVersionRow.organization_id)
                & (SavedReportStateRow.report_id == SavedReportVersionRow.report_id),
            )
            .where(
                SavedReportVersionRow.organization_id == organization_id,
                SavedReportVersionRow.report_id == report_id,
                SavedReportVersionRow.version == latest,
            )
        ).first()
        return (row[0], row[1]) if row else None

    def create(self, report: SavedReport) -> None:
        self.session.add(
            SavedReportIdentityRow(
                report_id=report.id,
                organization_id=report.organization_id,
                workspace_id=report.workspace_id,
                project_id=report.project_id,
                owner_id=report.owner_id,
                audit_id=report.audit_id,
            )
        )
        self.session.flush()
        self.session.add(
            SavedReportVersionRow(
                audit_id=report.audit_id,
                report_id=report.id,
                organization_id=report.organization_id,
                workspace_id=report.workspace_id,
                project_id=report.project_id,
                owner_id=report.owner_id,
                name=report.name,
                definition=report.definition.model_dump(mode="json"),
                version=report.version,
                definition_sha256=report.definition_sha256,
                created_at=report.created_at,
            )
        )
        self.session.flush()
        self.session.add(
            SavedReportStateRow(
                organization_id=report.organization_id,
                report_id=report.id,
                audit_id=report.audit_id,
                updated_at=report.updated_at,
                archived=False,
            )
        )
        self.session.flush()

    def get(self, organization_id: UUID, report_id: UUID) -> SavedReport | None:
        latest = self._latest(organization_id, report_id)
        return self._contract(*latest) if latest else None

    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID, cursor: UUID | None
    ) -> list[SavedReport]:
        latest_version = (
            select(
                SavedReportVersionRow.organization_id.label("organization_id"),
                SavedReportVersionRow.report_id.label("report_id"),
                func.max(SavedReportVersionRow.version).label("version"),
            )
            .where(
                SavedReportVersionRow.organization_id == organization_id,
                SavedReportVersionRow.report_id.in_(
                    select(SavedReportIdentityRow.report_id).where(
                        SavedReportIdentityRow.organization_id == organization_id,
                        SavedReportIdentityRow.workspace_id == workspace_id,
                        SavedReportIdentityRow.owner_id == owner_id,
                    )
                ),
            )
            .group_by(
                SavedReportVersionRow.organization_id,
                SavedReportVersionRow.report_id,
            )
            .subquery()
        )
        query = (
            select(SavedReportVersionRow, SavedReportStateRow)
            .join(
                SavedReportStateRow,
                (SavedReportStateRow.organization_id == SavedReportVersionRow.organization_id)
                & (SavedReportStateRow.report_id == SavedReportVersionRow.report_id),
            )
            .where(
                SavedReportVersionRow.organization_id == organization_id,
                SavedReportVersionRow.workspace_id == workspace_id,
                SavedReportVersionRow.owner_id == owner_id,
                SavedReportVersionRow.version == latest_version.c.version,
                SavedReportVersionRow.report_id == latest_version.c.report_id,
                SavedReportVersionRow.report_id.in_(
                    select(SavedReportIdentityRow.report_id).where(
                        SavedReportIdentityRow.organization_id == organization_id,
                        SavedReportIdentityRow.workspace_id == workspace_id,
                        SavedReportIdentityRow.owner_id == owner_id,
                    )
                ),
                SavedReportStateRow.archived.is_(False),
            )
            .order_by(SavedReportVersionRow.report_id)
            .limit(101)
        )
        if cursor is not None:
            query = query.where(SavedReportVersionRow.report_id > cursor)
        return [self._contract(version, state) for version, state in self.session.execute(query)]

    def append(self, report: SavedReport, expected_version: int) -> bool:
        row = self.session.scalar(
            select(SavedReportStateRow)
            .where(
                SavedReportStateRow.organization_id == report.organization_id,
                SavedReportStateRow.report_id == report.id,
                SavedReportStateRow.archived.is_(False),
            )
            .with_for_update()
        )
        current = self.get(report.organization_id, report.id)
        if (
            row is None
            or current is None
            or current.owner_id != report.owner_id
            or current.version != expected_version
        ):
            return False
        self.session.add(
            SavedReportVersionRow(
                audit_id=report.audit_id,
                report_id=report.id,
                organization_id=report.organization_id,
                workspace_id=report.workspace_id,
                project_id=report.project_id,
                owner_id=report.owner_id,
                name=report.name,
                definition=report.definition.model_dump(mode="json"),
                version=report.version,
                definition_sha256=report.definition_sha256,
                created_at=report.created_at,
            )
        )
        self.session.flush()
        result = self.session.execute(
            update(SavedReportStateRow)
            .where(
                SavedReportStateRow.organization_id == report.organization_id,
                SavedReportStateRow.report_id == report.id,
                SavedReportStateRow.archived.is_(False),
            )
            .values(audit_id=report.audit_id, updated_at=report.updated_at)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    def archive(
        self,
        organization_id: UUID,
        report_id: UUID,
        owner_id: UUID,
        expected: int,
        updated_at: datetime,
        audit_id: UUID,
    ) -> bool:
        current = self.get(organization_id, report_id)
        if (
            current is None
            or current.owner_id != owner_id
            or current.version != expected
            or current.archived
        ):
            return False
        result = self.session.execute(
            update(SavedReportStateRow)
            .where(
                SavedReportStateRow.organization_id == organization_id,
                SavedReportStateRow.report_id == report_id,
                SavedReportStateRow.audit_id == current.audit_id,
                SavedReportStateRow.archived.is_(False),
            )
            .values(audit_id=audit_id, updated_at=updated_at, archived=True)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1
