from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.workspaces.application.contracts import Workspace
from operations.platform.database import Base


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool]
    version: Mapped[int]


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, organization_id: UUID, workspace_id: UUID) -> Workspace | None:
        row = self.session.scalar(
            select(WorkspaceRow).where(
                WorkspaceRow.organization_id == organization_id,
                WorkspaceRow.id == workspace_id,
            )
        )
        return (
            Workspace(row.id, row.organization_id, row.name, row.active, row.version)
            if row
            else None
        )

    def create(self, workspace: Workspace) -> None:
        self.session.add(
            WorkspaceRow(
                id=workspace.id,
                organization_id=workspace.organization_id,
                name=workspace.name,
                active=workspace.active,
                version=workspace.version,
            )
        )
        self.session.flush()

    def update(self, workspace: Workspace, expected_version: int) -> bool:
        result = self.session.execute(
            update(WorkspaceRow)
            .where(
                WorkspaceRow.organization_id == workspace.organization_id,
                WorkspaceRow.id == workspace.id,
                WorkspaceRow.version == expected_version,
            )
            .values(name=workspace.name, active=workspace.active, version=workspace.version)
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def list(
        self,
        organization_id: UUID,
        workspace_ids: list[UUID] | None,
        after: UUID | None,
    ) -> list[Workspace]:
        query = select(WorkspaceRow).where(
            WorkspaceRow.organization_id == organization_id,
            WorkspaceRow.active.is_(True),
        )
        if workspace_ids is not None:
            query = query.where(WorkspaceRow.id.in_(workspace_ids))
        if after is not None:
            query = query.where(WorkspaceRow.id > after)
        rows = self.session.scalars(query.order_by(WorkspaceRow.id).limit(101))
        return [
            Workspace(row.id, row.organization_id, row.name, row.active, row.version)
            for row in rows
        ]
