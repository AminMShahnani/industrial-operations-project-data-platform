from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    select,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.iam.application.contracts import Grant, Role, ScopeType
from operations.platform.database import Base


class GrantRow(Base):
    __tablename__ = "grants"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id", "user_id"], ["users.organization_id", "users.id"]),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        CheckConstraint(
            "(scope_type = 'organization' AND scope_id = organization_id AND workspace_id IS NULL) "
            "OR (scope_type = 'workspace' AND workspace_id IS NOT NULL "
            "AND workspace_id = scope_id)",
            name="grant_scope",
        ),
        CheckConstraint("NOT inherit OR scope_type = 'organization'", name="inherit_scope"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="validity_window",
        ),
        Index("ix_grants_tenant_user", "organization_id", "user_id", "revoked"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    user_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(40))
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[UUID]
    workspace_id: Mapped[UUID | None]
    inherit: Mapped[bool]
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool]


def contract(row: GrantRow) -> Grant:
    return Grant(
        row.id,
        row.organization_id,
        row.user_id,
        Role(row.role),
        ScopeType(row.scope_type),
        row.scope_id,
        row.inherit,
        row.valid_from,
        row.valid_until,
        row.revoked,
    )


class GrantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_user(self, organization_id: UUID, user_id: UUID) -> list[Grant]:
        rows = self.session.scalars(
            select(GrantRow)
            .where(
                GrantRow.organization_id == organization_id,
                GrantRow.user_id == user_id,
            )
            .with_for_update()
        )
        return [contract(row) for row in rows]

    def create(self, grant: Grant) -> None:
        self.session.add(
            GrantRow(
                id=grant.id,
                organization_id=grant.organization_id,
                user_id=grant.user_id,
                role=grant.role,
                scope_type=grant.scope_type,
                scope_id=grant.scope_id,
                workspace_id=grant.scope_id if grant.scope_type == ScopeType.WORKSPACE else None,
                inherit=grant.inherit,
                valid_from=grant.valid_from,
                valid_until=grant.valid_until,
                revoked=grant.revoked,
            )
        )
        self.session.flush()

    def get(self, organization_id: UUID, grant_id: UUID) -> Grant | None:
        row = self.session.scalar(
            select(GrantRow)
            .where(
                GrantRow.organization_id == organization_id,
                GrantRow.id == grant_id,
            )
            .with_for_update()
        )
        return contract(row) if row else None

    def revoke(self, organization_id: UUID, grant_id: UUID) -> None:
        self.session.execute(
            update(GrantRow)
            .where(
                GrantRow.organization_id == organization_id,
                GrantRow.id == grant_id,
            )
            .values(revoked=True)
        )
