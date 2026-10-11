"""Durable private report export job persistence."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    and_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.reporting.application.contracts import ReportExportJob
from operations.platform.database import Base


class ReportExportJobRow(Base):
    __tablename__ = "report_export_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "report_id"],
            ["saved_report_identities.organization_id", "saved_report_identities.report_id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        Index(
            "ix_report_export_owner", "organization_id", "workspace_id", "owner_id", "created_at"
        ),
        Index("ix_report_export_recovery", "state", "updated_at", "expires_at"),
        CheckConstraint("report_version > 0", name="report_export_version_positive"),
        CheckConstraint(
            "state IN ('pending','running','completed','failed','expired','revoked')",
            name="report_export_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    report_id: Mapped[UUID]
    report_version: Mapped[int]
    report_digest: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16))
    format: Mapped[str] = mapped_column(String(8))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    artifact_key: Mapped[str | None] = mapped_column(String(500))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_size: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(80))


def contract(row: ReportExportJobRow) -> ReportExportJob:
    return ReportExportJob(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        owner_id=row.owner_id,
        report_id=row.report_id,
        report_version=row.report_version,
        report_digest=row.report_digest,
        scope=row.scope,  # type: ignore[arg-type]
        format=row.format,  # type: ignore[arg-type]
        state=row.state,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
        artifact_key=row.artifact_key,
        artifact_sha256=row.artifact_sha256,
        artifact_size=row.artifact_size,
        error_code=row.error_code,
    )


class ReportExportJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, job: ReportExportJob, definition: dict[str, object]) -> None:
        self.session.add(ReportExportJobRow(**job.model_dump(), definition=definition))
        self.session.flush()

    def get(
        self, organization_id: UUID, job_id: UUID, lock: bool = False
    ) -> ReportExportJob | None:
        query = select(ReportExportJobRow).where(
            ReportExportJobRow.organization_id == organization_id,
            ReportExportJobRow.id == job_id,
        )
        if lock:
            query = query.with_for_update()
        row = self.session.scalar(query)
        return contract(row) if row else None

    def page(
        self, organization_id: UUID, workspace_id: UUID, owner_id: UUID
    ) -> list[ReportExportJob]:
        rows = self.session.scalars(
            select(ReportExportJobRow)
            .where(
                ReportExportJobRow.organization_id == organization_id,
                ReportExportJobRow.workspace_id == workspace_id,
                ReportExportJobRow.owner_id == owner_id,
                ReportExportJobRow.expires_at > datetime.now(UTC),
            )
            .order_by(ReportExportJobRow.created_at.desc(), ReportExportJobRow.id.desc())
            .limit(100)
        )
        return [contract(row) for row in rows]

    def artifact_definition(
        self, organization_id: UUID, job_id: UUID
    ) -> tuple[str | None, dict[str, object] | None]:
        row = self.session.execute(
            select(ReportExportJobRow.artifact_key, ReportExportJobRow.definition).where(
                ReportExportJobRow.organization_id == organization_id,
                ReportExportJobRow.id == job_id,
            )
        ).first()
        return (row[0], row[1]) if row else (None, None)

    def save(self, job: ReportExportJob, expected_state: str) -> bool:
        result = self.session.execute(
            update(ReportExportJobRow)
            .where(
                ReportExportJobRow.organization_id == job.organization_id,
                ReportExportJobRow.id == job.id,
                ReportExportJobRow.state == expected_state,
            )
            .values(
                state=job.state,
                updated_at=job.updated_at,
                artifact_key=job.artifact_key,
                artifact_sha256=job.artifact_sha256,
                artifact_size=job.artifact_size,
                error_code=job.error_code,
            )
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    def claim(self, organization_id: UUID, job_id: UUID, now: datetime) -> ReportExportJob | None:
        row = self.session.scalar(
            select(ReportExportJobRow)
            .where(
                ReportExportJobRow.organization_id == organization_id,
                ReportExportJobRow.id == job_id,
            )
            .with_for_update()
        )
        if row is None or row.expires_at <= now or row.state in {"completed", "expired", "revoked"}:
            return None
        if row.state == "running" and row.updated_at > now - timedelta(minutes=5):
            return None
        if row.state == "running":
            row.error_code = "previous_attempt_interrupted"
        row.state = "running"
        row.updated_at = now
        self.session.flush()
        return contract(row)

    def definition(self, organization_id: UUID, job_id: UUID) -> dict[str, object] | None:
        row = self.session.scalar(
            select(ReportExportJobRow.definition).where(
                ReportExportJobRow.organization_id == organization_id,
                ReportExportJobRow.id == job_id,
            )
        )
        return row

    def due(self, now: datetime) -> list[tuple[UUID, UUID]]:
        rows = self.session.execute(
            select(ReportExportJobRow.organization_id, ReportExportJobRow.id)
            .where(
                ReportExportJobRow.expires_at > now,
                or_(
                    ReportExportJobRow.state == "pending",
                    and_(
                        ReportExportJobRow.state == "running",
                        ReportExportJobRow.updated_at <= now - timedelta(minutes=5),
                    ),
                ),
            )
            .order_by(ReportExportJobRow.created_at, ReportExportJobRow.id)
            .limit(100)
        )
        return [(org, identifier) for org, identifier in rows]

    def expired_artifacts(self, now: datetime) -> list[tuple[UUID, UUID, str]]:
        rows = self.session.execute(
            select(
                ReportExportJobRow.organization_id,
                ReportExportJobRow.id,
                ReportExportJobRow.artifact_key,
            )
            .where(
                ReportExportJobRow.state == "completed",
                ReportExportJobRow.expires_at <= now,
                ReportExportJobRow.artifact_key.is_not(None),
            )
            .limit(100)
        )
        return [(org, identifier, key) for org, identifier, key in rows if key is not None]

    def expire(self, organization_id: UUID, job_id: UUID, now: datetime) -> bool:
        result = self.session.execute(
            update(ReportExportJobRow)
            .where(
                ReportExportJobRow.organization_id == organization_id,
                ReportExportJobRow.id == job_id,
                ReportExportJobRow.state == "completed",
                ReportExportJobRow.expires_at <= now,
            )
            .values(state="expired", updated_at=now)
        )
        return isinstance(result, CursorResult) and result.rowcount == 1

    def expire_due(self, now: datetime) -> list[ReportExportJob]:
        rows = list(
            self.session.scalars(
                select(ReportExportJobRow)
                .where(
                    ReportExportJobRow.expires_at <= now,
                    ReportExportJobRow.state.in_(("pending", "running", "failed")),
                )
                .order_by(ReportExportJobRow.expires_at, ReportExportJobRow.id)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        jobs: list[ReportExportJob] = []
        for row in rows:
            job = contract(row)
            row.state = "expired"
            row.updated_at = now
            jobs.append(job)
        return jobs
