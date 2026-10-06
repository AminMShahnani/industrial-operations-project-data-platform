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

from operations.modules.projects.application.contracts import (
    DepartmentProjectGrant,
    LifecycleDefinition,
    Milestone,
    Project,
    ProjectContext,
    ProjectMembership,
    ProjectRole,
)
from operations.platform.database import Base


class MilestoneRow(Base):
    __tablename__ = "project_milestones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_projects_scope_identity"
        ),
        Index("ix_projects_scope_state", "organization_id", "workspace_id", "state", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(40))
    lifecycle: Mapped[dict[str, object]] = mapped_column(JSONB)
    context: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int]


class ProjectMembershipRow(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(["organization_id", "user_id"], ["users.organization_id", "users.id"]),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="validity_window",
        ),
        CheckConstraint("role IN ('ProjectManager', 'Contributor', 'Viewer')", name="project_role"),
        Index(
            "ix_project_memberships_scope_user",
            "organization_id",
            "workspace_id",
            "user_id",
            "revoked",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID]
    user_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(40))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool]


class DepartmentProjectGrantRow(Base):
    __tablename__ = "department_project_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "department_id", "department_kind"],
            [
                "workspace_groups.organization_id",
                "workspace_groups.workspace_id",
                "workspace_groups.id",
                "workspace_groups.kind",
            ],
        ),
        CheckConstraint("department_kind = 'department'", name="department_kind"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="validity_window",
        ),
        CheckConstraint("role IN ('ProjectManager', 'Contributor', 'Viewer')", name="project_role"),
        Index(
            "ix_department_project_grants_scope",
            "organization_id",
            "workspace_id",
            "department_id",
            "revoked",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID]
    department_id: Mapped[UUID]
    department_kind: Mapped[str] = mapped_column(String(20), server_default=text("'department'"))
    role: Mapped[str] = mapped_column(String(40))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool]


def project_contract(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        name=row.name,
        state=row.state,
        lifecycle=LifecycleDefinition.model_validate(row.lifecycle),
        context=ProjectContext.model_validate(row.context),
        version=row.version,
    )


def membership_contract(row: ProjectMembershipRow) -> ProjectMembership:
    return ProjectMembership(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        user_id=row.user_id,
        role=ProjectRole(row.role),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        revoked=row.revoked,
    )


def department_contract(row: DepartmentProjectGrantRow) -> DepartmentProjectGrant:
    return DepartmentProjectGrant(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        department_id=row.department_id,
        role=ProjectRole(row.role),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        revoked=row.revoked,
    )


class ProjectRepository:
    def add_milestone(self, row: Milestone) -> None:
        self.session.add(MilestoneRow(**row.model_dump()))
        self.session.flush()

    def milestone(
        self, org: UUID, workspace: UUID, project: UUID, identifier: UUID
    ) -> Milestone | None:
        row = self.session.scalar(
            select(MilestoneRow).where(
                MilestoneRow.organization_id == org,
                MilestoneRow.workspace_id == workspace,
                MilestoneRow.project_id == project,
                MilestoneRow.id == identifier,
            )
        )
        return (
            Milestone.model_validate({k: getattr(row, k) for k in Milestone.model_fields})
            if row
            else None
        )

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, organization_id: UUID, workspace_id: UUID, project_id: UUID) -> Project | None:
        row = self.session.scalar(
            select(ProjectRow)
            .where(
                ProjectRow.organization_id == organization_id,
                ProjectRow.workspace_id == workspace_id,
                ProjectRow.id == project_id,
            )
            .with_for_update()
        )
        return project_contract(row) if row else None

    def create(self, project: Project) -> None:
        self.session.add(
            ProjectRow(
                id=project.id,
                organization_id=project.organization_id,
                workspace_id=project.workspace_id,
                name=project.name,
                state=project.state,
                lifecycle=project.lifecycle.model_dump(mode="json"),
                context=project.context.model_dump(mode="json"),
                version=project.version,
            )
        )
        self.session.flush()

    def update(self, project: Project, expected_version: int) -> bool:
        result = self.session.execute(
            update(ProjectRow)
            .where(
                ProjectRow.organization_id == project.organization_id,
                ProjectRow.workspace_id == project.workspace_id,
                ProjectRow.id == project.id,
                ProjectRow.version == expected_version,
            )
            .values(
                name=project.name,
                state=project.state,
                context=project.context.model_dump(mode="json"),
                version=project.version,
            )
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def list_projects(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        visible: list[UUID] | None,
        after: UUID | None,
    ) -> list[Project]:
        query = select(ProjectRow).where(
            ProjectRow.organization_id == organization_id, ProjectRow.workspace_id == workspace_id
        )
        if visible is not None:
            query = query.where(ProjectRow.id.in_(visible))
        if after is not None:
            query = query.where(ProjectRow.id > after)
        return [
            project_contract(row)
            for row in self.session.scalars(query.order_by(ProjectRow.id).limit(101))
        ]

    def memberships(self, organization_id: UUID, user_id: UUID) -> list[ProjectMembership]:
        return [
            membership_contract(row)
            for row in self.session.scalars(
                select(ProjectMembershipRow).where(
                    ProjectMembershipRow.organization_id == organization_id,
                    ProjectMembershipRow.user_id == user_id,
                )
            )
        ]

    def add_membership(self, membership: ProjectMembership) -> None:
        self.session.add(ProjectMembershipRow(**membership.model_dump()))
        self.session.flush()

    def membership(
        self, organization_id: UUID, project_id: UUID, membership_id: UUID
    ) -> ProjectMembership | None:
        row = self.session.scalar(
            select(ProjectMembershipRow)
            .where(
                ProjectMembershipRow.organization_id == organization_id,
                ProjectMembershipRow.project_id == project_id,
                ProjectMembershipRow.id == membership_id,
            )
            .with_for_update()
        )
        return membership_contract(row) if row else None

    def revoke_membership(self, organization_id: UUID, membership_id: UUID) -> None:
        self.session.execute(
            update(ProjectMembershipRow)
            .where(
                ProjectMembershipRow.organization_id == organization_id,
                ProjectMembershipRow.id == membership_id,
            )
            .values(revoked=True)
        )

    def department_grants(
        self, organization_id: UUID, department_ids: list[UUID]
    ) -> list[DepartmentProjectGrant]:
        return [
            department_contract(row)
            for row in self.session.scalars(
                select(DepartmentProjectGrantRow).where(
                    DepartmentProjectGrantRow.organization_id == organization_id,
                    DepartmentProjectGrantRow.department_id.in_(department_ids),
                )
            )
        ]

    def add_department_grant(self, grant: DepartmentProjectGrant) -> None:
        self.session.add(DepartmentProjectGrantRow(**grant.model_dump()))
        self.session.flush()

    def department_grant(
        self, organization_id: UUID, project_id: UUID, grant_id: UUID
    ) -> DepartmentProjectGrant | None:
        row = self.session.scalar(
            select(DepartmentProjectGrantRow)
            .where(
                DepartmentProjectGrantRow.organization_id == organization_id,
                DepartmentProjectGrantRow.project_id == project_id,
                DepartmentProjectGrantRow.id == grant_id,
            )
            .with_for_update()
        )
        return department_contract(row) if row else None

    def revoke_department_grant(self, organization_id: UUID, grant_id: UUID) -> None:
        self.session.execute(
            update(DepartmentProjectGrantRow)
            .where(
                DepartmentProjectGrantRow.organization_id == organization_id,
                DepartmentProjectGrantRow.id == grant_id,
            )
            .values(revoked=True)
        )
