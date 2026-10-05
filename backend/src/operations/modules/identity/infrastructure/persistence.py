from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.identity.application.contracts import Invitation, Principal, User
from operations.platform.database import Base


class PlatformAdminRow(Base):
    __tablename__ = "platform_admins"
    issuer: Mapped[str] = mapped_column(String(500), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    active: Mapped[bool]


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "issuer", "subject", name="uq_users_tenant_identity"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    active: Mapped[bool]


class InvitationRow(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "inviter_id"], ["users.organization_id", "users.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(40))
    scope_id: Mapped[UUID]
    scope_type: Mapped[str] = mapped_column(String(20))
    workspace_id: Mapped[UUID | None]
    inviter_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def user_contract(row: UserRow) -> User:
    return User(row.id, row.organization_id, row.issuer, row.subject, row.email, row.active)


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def platform_admin(self, principal: Principal) -> bool:
        row = self.session.get(PlatformAdminRow, (principal.issuer, principal.subject))
        return bool(row and row.active)

    def bootstrap(self, principal: Principal) -> None:
        self.session.add(
            PlatformAdminRow(issuer=principal.issuer, subject=principal.subject, active=True)
        )
        self.session.flush()

    def user(self, organization_id: UUID, principal: Principal) -> User | None:
        row = self.session.scalar(
            select(UserRow)
            .where(
                UserRow.organization_id == organization_id,
                UserRow.issuer == principal.issuer,
                UserRow.subject == principal.subject,
            )
            .with_for_update()
        )
        return user_contract(row) if row else None

    def by_id(self, organization_id: UUID, user_id: UUID) -> User | None:
        row = self.session.scalar(
            select(UserRow)
            .where(
                UserRow.organization_id == organization_id,
                UserRow.id == user_id,
            )
            .with_for_update()
        )
        return user_contract(row) if row else None

    def memberships(self, principal: Principal) -> list[User]:
        rows = self.session.scalars(
            select(UserRow)
            .where(
                UserRow.issuer == principal.issuer,
                UserRow.subject == principal.subject,
                UserRow.active.is_(True),
            )
            .order_by(UserRow.id)
            .limit(100)
        )
        return [user_contract(row) for row in rows]

    def create_user(self, user: User) -> None:
        self.session.add(
            UserRow(
                id=user.id,
                organization_id=user.organization_id,
                issuer=user.issuer,
                subject=user.subject,
                email=user.email,
                active=user.active,
            )
        )
        self.session.flush()

    def set_active(self, organization_id: UUID, user_id: UUID, active: bool) -> None:
        self.session.execute(
            update(UserRow)
            .where(
                UserRow.organization_id == organization_id,
                UserRow.id == user_id,
            )
            .values(active=active)
        )

    def invite(self, invitation: Invitation) -> None:
        self.session.add(
            InvitationRow(
                id=invitation.id,
                organization_id=invitation.organization_id,
                email=invitation.email,
                token_digest=invitation.token_digest,
                role=invitation.role,
                scope_id=invitation.scope_id,
                scope_type=invitation.scope_type,
                workspace_id=invitation.scope_id if invitation.scope_type == "workspace" else None,
                inviter_id=invitation.inviter_id,
                expires_at=invitation.expires_at,
                accepted_at=None,
            )
        )
        self.session.flush()

    def invitation(self, organization_id: UUID, token_digest: str) -> Invitation | None:
        row = self.session.scalar(
            select(InvitationRow)
            .where(
                InvitationRow.organization_id == organization_id,
                InvitationRow.token_digest == token_digest,
            )
            .with_for_update()
        )
        if row is None:
            return None
        return Invitation(
            row.id,
            row.organization_id,
            row.email,
            row.token_digest,
            row.role,
            row.scope_id,
            row.scope_type,
            row.inviter_id,
            row.expires_at,
            row.accepted_at,
        )

    def accept(self, organization_id: UUID, invitation_id: UUID, accepted_at: datetime) -> None:
        self.session.execute(
            update(InvitationRow)
            .where(
                InvitationRow.organization_id == organization_id,
                InvitationRow.id == invitation_id,
            )
            .values(accepted_at=accepted_at)
        )
