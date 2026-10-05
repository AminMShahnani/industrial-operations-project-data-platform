from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.workspaces.application.groups import Group, GroupKind, GroupMembership
from operations.platform.database import Base


class GroupRow(Base):
    __tablename__ = "workspace_groups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_workspace_groups_scope_identity"
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", "kind", name="uq_workspace_groups_scope_kind"
        ),
        CheckConstraint("kind IN ('department', 'team')", name="group_kind"),
        Index(
            "ix_workspace_groups_scope_active", "organization_id", "workspace_id", "active", "id"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool]
    version: Mapped[int]


class GroupMembershipRow(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "group_id"],
            [
                "workspace_groups.organization_id",
                "workspace_groups.workspace_id",
                "workspace_groups.id",
            ],
        ),
        ForeignKeyConstraint(["organization_id", "user_id"], ["users.organization_id", "users.id"]),
        Index(
            "ix_group_memberships_scope_user",
            "organization_id",
            "workspace_id",
            "user_id",
            "active",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    group_id: Mapped[UUID]
    user_id: Mapped[UUID]
    manager: Mapped[bool]
    active: Mapped[bool]


def group_contract(row: GroupRow) -> Group:
    return Group(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        kind=GroupKind(row.kind),
        name=row.name,
        active=row.active,
        version=row.version,
    )


def member_contract(row: GroupMembershipRow) -> GroupMembership:
    return GroupMembership(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        group_id=row.group_id,
        user_id=row.user_id,
        manager=row.manager,
        active=row.active,
    )


class GroupRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def active_memberships_for_user(
        self, organization_id: UUID, user_id: UUID
    ) -> list[GroupMembership]:
        return [
            member_contract(row)
            for row in self.session.scalars(
                select(GroupMembershipRow).where(
                    GroupMembershipRow.organization_id == organization_id,
                    GroupMembershipRow.user_id == user_id,
                    GroupMembershipRow.active.is_(True),
                )
            )
        ]

    def get(self, organization_id: UUID, workspace_id: UUID, group_id: UUID) -> Group | None:
        row = self.session.scalar(
            select(GroupRow)
            .where(
                GroupRow.organization_id == organization_id,
                GroupRow.workspace_id == workspace_id,
                GroupRow.id == group_id,
            )
            .with_for_update()
        )
        return group_contract(row) if row else None

    def create(self, group: Group) -> None:
        self.session.add(GroupRow(**group.model_dump()))
        self.session.flush()

    def update(self, group: Group, expected_version: int) -> bool:
        result = self.session.execute(
            update(GroupRow)
            .where(
                GroupRow.organization_id == group.organization_id,
                GroupRow.workspace_id == group.workspace_id,
                GroupRow.id == group.id,
                GroupRow.version == expected_version,
            )
            .values(name=group.name, active=group.active, version=group.version)
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def list_groups(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        after: UUID | None,
        visible: list[UUID] | None = None,
    ) -> list[Group]:
        query = select(GroupRow).where(
            GroupRow.organization_id == organization_id, GroupRow.workspace_id == workspace_id
        )
        if after is not None:
            query = query.where(GroupRow.id > after)
        if visible is not None:
            query = query.where(GroupRow.id.in_(visible))
        return [
            group_contract(row)
            for row in self.session.scalars(query.order_by(GroupRow.id).limit(101))
        ]

    def membership(
        self, organization_id: UUID, group_id: UUID, membership_id: UUID
    ) -> GroupMembership | None:
        row = self.session.scalar(
            select(GroupMembershipRow)
            .where(
                GroupMembershipRow.organization_id == organization_id,
                GroupMembershipRow.group_id == group_id,
                GroupMembershipRow.id == membership_id,
            )
            .with_for_update()
        )
        return member_contract(row) if row else None

    def add_membership(self, membership: GroupMembership) -> None:
        self.session.add(GroupMembershipRow(**membership.model_dump()))
        self.session.flush()

    def revoke(self, organization_id: UUID, membership_id: UUID) -> None:
        self.session.execute(
            update(GroupMembershipRow)
            .where(
                GroupMembershipRow.organization_id == organization_id,
                GroupMembershipRow.id == membership_id,
            )
            .values(active=False)
        )

    def memberships(
        self, organization_id: UUID, workspace_id: UUID, user_id: UUID
    ) -> list[GroupMembership]:
        return [
            member_contract(row)
            for row in self.session.scalars(
                select(GroupMembershipRow).where(
                    GroupMembershipRow.organization_id == organization_id,
                    GroupMembershipRow.workspace_id == workspace_id,
                    GroupMembershipRow.user_id == user_id,
                    GroupMembershipRow.active.is_(True),
                )
            )
        ]
