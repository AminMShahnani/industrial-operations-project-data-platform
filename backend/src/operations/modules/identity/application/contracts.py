from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False


@dataclass(frozen=True)
class RequestContext:
    principal: Principal
    request_id: UUID
    correlation_id: UUID


@dataclass(frozen=True)
class User:
    id: UUID
    organization_id: UUID
    issuer: str
    subject: str
    email: str
    active: bool


@dataclass(frozen=True)
class Invitation:
    id: UUID
    organization_id: UUID
    email: str
    token_digest: str | None
    role: str
    scope_id: UUID
    scope_type: str
    inviter_id: UUID
    expires_at: datetime
    accepted_at: datetime | None
    acceptance_mode: Literal["token", "verified_email"] = "token"


class IdentityStore(Protocol):
    def active_users(self, organization_id: UUID, after: UUID | None) -> list[User]: ...
    def platform_admin(self, principal: Principal) -> bool: ...
    def bootstrap(self, principal: Principal) -> None: ...
    def user(self, organization_id: UUID, principal: Principal) -> User | None: ...
    def by_id(self, organization_id: UUID, user_id: UUID) -> User | None: ...
    def memberships(self, principal: Principal) -> list[User]: ...
    def active_by_email(self, organization_id: UUID, email: str) -> list[User]: ...
    def create_user(self, user: User) -> None: ...
    def set_active(self, organization_id: UUID, user_id: UUID, active: bool) -> None: ...
    def invite(self, invitation: Invitation) -> None: ...
    def invitation(self, organization_id: UUID, token_digest: str) -> Invitation | None: ...
    def invitation_by_id(self, organization_id: UUID, identifier: UUID) -> Invitation | None: ...
    def accept(self, organization_id: UUID, invitation_id: UUID, accepted_at: datetime) -> None: ...


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Principal: ...


class AccessRevoker(Protocol):
    def revoke_user_access(
        self, context: RequestContext, organization_id: UUID, user_id: UUID
    ) -> None: ...
