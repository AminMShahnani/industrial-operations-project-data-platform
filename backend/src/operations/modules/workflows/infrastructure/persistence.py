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

from operations.modules.workflows.application.contracts import Workflow, WorkflowVersion
from operations.platform.database import Base


class WorkflowRow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("organization_id", "workspace_id", "id", name="uq_workflows_scope"),
        CheckConstraint(
            "revision > 0 AND (active_number IS NULL OR active_number > 0)",
            name="workflow_revision",
        ),
        Index("ix_workflows_scope_cursor", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(120))
    active_number: Mapped[int | None]
    revision: Mapped[int]


class WorkflowVersionRow(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "workflow_id"],
            ["workflows.organization_id", "workflows.workspace_id", "workflows.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_version_id"],
            ["form_versions.organization_id", "form_versions.workspace_id", "form_versions.id"],
        ),
        UniqueConstraint(
            "organization_id", "workflow_id", "number", name="uq_workflow_version_number"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "workflow_id",
            "id",
            "number",
            name="uq_workflow_version_exact",
        ),
        CheckConstraint(
            "number > 0 AND revision > 0 AND state IN ('draft','active','retired')",
            name="workflow_version_state",
        ),
        CheckConstraint(
            "(state='draft' AND activated_at IS NULL AND content_sha256 IS NULL "
            "AND form_version_id IS NULL) OR (state<>'draft' AND activated_at IS NOT NULL "
            "AND content_sha256 IS NOT NULL AND form_version_id IS NOT NULL)",
            name="workflow_activation",
        ),
        Index(
            "ix_workflow_versions_cursor", "organization_id", "workspace_id", "workflow_id", "id"
        ),
        Index(
            "uq_workflow_active_form",
            "organization_id",
            "workspace_id",
            "form_version_id",
            unique=True,
            postgresql_where=text("state='active'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    workflow_id: Mapped[UUID]
    number: Mapped[int]
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int]
    form_version_id: Mapped[UUID | None]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


def workflow_contract(row: WorkflowRow) -> Workflow:
    return Workflow.model_validate({name: getattr(row, name) for name in Workflow.model_fields})


def version_contract(row: WorkflowVersionRow) -> WorkflowVersion:
    return WorkflowVersion.model_validate(
        {name: getattr(row, name) for name in WorkflowVersion.model_fields}
    )


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def active_for_form(
        self, org: UUID, workspace: UUID, form_version: UUID
    ) -> WorkflowVersion | None:
        row = self.session.scalar(
            select(WorkflowVersionRow).where(
                WorkflowVersionRow.organization_id == org,
                WorkflowVersionRow.workspace_id == workspace,
                WorkflowVersionRow.form_version_id == form_version,
                WorkflowVersionRow.state == "active",
            )
        )
        return version_contract(row) if row else None

    def create(self, workflow: Workflow) -> None:
        self.session.add(WorkflowRow(**workflow.model_dump()))
        self.session.flush()

    def get(
        self, org: UUID, workspace: UUID, identifier: UUID, lock: bool = False
    ) -> Workflow | None:
        query = select(WorkflowRow).where(
            WorkflowRow.organization_id == org,
            WorkflowRow.workspace_id == workspace,
            WorkflowRow.id == identifier,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return workflow_contract(row) if row else None

    def list_workflows(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Workflow]:
        query = select(WorkflowRow).where(
            WorkflowRow.organization_id == org,
            WorkflowRow.workspace_id == workspace,
            WorkflowRow.project_id == project,
        )
        if after:
            query = query.where(WorkflowRow.id > after)
        return [
            workflow_contract(row)
            for row in self.session.scalars(query.order_by(WorkflowRow.id).limit(101))
        ]

    def save(self, workflow: Workflow, expected: int) -> bool:
        identifier = self.session.scalar(
            update(WorkflowRow)
            .where(
                WorkflowRow.organization_id == workflow.organization_id,
                WorkflowRow.workspace_id == workflow.workspace_id,
                WorkflowRow.id == workflow.id,
                WorkflowRow.revision == expected,
            )
            .values(active_number=workflow.active_number, revision=workflow.revision)
            .returning(WorkflowRow.id)
        )
        self.session.flush()
        return identifier is not None

    def add_version(self, version: WorkflowVersion) -> None:
        values = version.model_dump()
        values["definition"] = version.definition.model_dump(mode="json")
        self.session.add(WorkflowVersionRow(**values))
        self.session.flush()

    def version(
        self, org: UUID, workspace: UUID, identifier: UUID, number: int, lock: bool = False
    ) -> WorkflowVersion | None:
        query = select(WorkflowVersionRow).where(
            WorkflowVersionRow.organization_id == org,
            WorkflowVersionRow.workspace_id == workspace,
            WorkflowVersionRow.workflow_id == identifier,
            WorkflowVersionRow.number == number,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return version_contract(row) if row else None

    def versions(
        self, org: UUID, workspace: UUID, identifier: UUID, after: UUID | None
    ) -> list[WorkflowVersion]:
        query = select(WorkflowVersionRow).where(
            WorkflowVersionRow.organization_id == org,
            WorkflowVersionRow.workspace_id == workspace,
            WorkflowVersionRow.workflow_id == identifier,
        )
        if after:
            query = query.where(WorkflowVersionRow.id > after)
        return [
            version_contract(row)
            for row in self.session.scalars(query.order_by(WorkflowVersionRow.id).limit(101))
        ]

    def save_version(self, version: WorkflowVersion, expected: int) -> bool:
        values = version.model_dump(
            exclude={"id", "organization_id", "workspace_id", "workflow_id", "number"}
        )
        values["definition"] = version.definition.model_dump(mode="json")
        identifier = self.session.scalar(
            update(WorkflowVersionRow)
            .where(
                WorkflowVersionRow.organization_id == version.organization_id,
                WorkflowVersionRow.workspace_id == version.workspace_id,
                WorkflowVersionRow.id == version.id,
                WorkflowVersionRow.revision == expected,
            )
            .values(**values)
            .returning(WorkflowVersionRow.id)
        )
        self.session.flush()
        return identifier is not None
