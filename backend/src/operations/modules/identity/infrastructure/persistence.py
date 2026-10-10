from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.identity.application.contracts import Invitation, Principal, User
from operations.modules.organizations.application.contracts import OrganizationLock
from operations.platform.database import Base


class PlatformAdminRow(Base):
    __tablename__ = "platform_admins"
    issuer: Mapped[str] = mapped_column(String(500), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    active: Mapped[bool]


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_scope_email_active", "organization_id", "email", "active", "id"),
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
        CheckConstraint(
            "(acceptance_mode = 'token' AND token_digest IS NOT NULL) OR "
            "(acceptance_mode = 'verified_email' AND token_digest IS NULL)",
            name="ck_invitation_acceptance_credentials",
        ),
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
    token_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    acceptance_mode: Mapped[str] = mapped_column(String(20), server_default="token")
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
    def active_users(self, organization_id: UUID, after: UUID | None) -> list[User]:
        query = select(UserRow).where(
            UserRow.organization_id == organization_id, UserRow.active.is_(True)
        )
        if after:
            query = query.where(UserRow.id > after)
        return [
            User(row.id, row.organization_id, row.issuer, row.subject, row.email, row.active)
            for row in self.session.scalars(query.order_by(UserRow.id).limit(101))
        ]

    def __init__(self, session: Session, organizations: OrganizationLock) -> None:
        self.session = session
        self.organizations = organizations

    def active_by_email(self, organization_id: UUID, email: str) -> list[User]:
        return [
            user_contract(row)
            for row in self.session.scalars(
                select(UserRow)
                .where(
                    UserRow.organization_id == organization_id,
                    UserRow.email == email.casefold(),
                    UserRow.active.is_(True),
                )
                .order_by(UserRow.id)
                .limit(10)
            )
        ]

    def platform_admin(self, principal: Principal) -> bool:
        row = self.session.get(PlatformAdminRow, (principal.issuer, principal.subject))
        return bool(row and row.active)

    def bootstrap(self, principal: Principal) -> None:
        self.session.add(
            PlatformAdminRow(issuer=principal.issuer, subject=principal.subject, active=True)
        )
        self.session.flush()

    def user(self, organization_id: UUID, principal: Principal) -> User | None:
        self.organizations.lock(organization_id)
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
        self.organizations.lock(organization_id)
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
                acceptance_mode=invitation.acceptance_mode,
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
        self.organizations.lock(organization_id)
        row = self.session.scalar(
            select(InvitationRow)
            .where(
                InvitationRow.organization_id == organization_id,
                InvitationRow.token_digest == token_digest,
                InvitationRow.acceptance_mode == "token",
            )
            .with_for_update()
        )
        if row is None:
            return None
        return invitation_contract(row)

    def invitation_by_id(self, organization_id: UUID, identifier: UUID) -> Invitation | None:
        self.organizations.lock(organization_id)
        row = self.session.scalar(
            select(InvitationRow)
            .where(InvitationRow.organization_id == organization_id, InvitationRow.id == identifier)
            .with_for_update()
        )
        return invitation_contract(row) if row else None

    def accept(self, organization_id: UUID, invitation_id: UUID, accepted_at: datetime) -> None:
        self.session.execute(
            update(InvitationRow)
            .where(
                InvitationRow.organization_id == organization_id,
                InvitationRow.id == invitation_id,
            )
            .values(accepted_at=accepted_at)
        )


def invitation_contract(row: InvitationRow) -> Invitation:
    if row.acceptance_mode not in {"token", "verified_email"}:
        raise ValueError("Invalid persisted invitation mode")
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
        "verified_email" if row.acceptance_mode == "verified_email" else "token",
    )
