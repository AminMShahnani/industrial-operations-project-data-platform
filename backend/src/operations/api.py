from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid7

from fastapi import APIRouter, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from operations.composition import Services, compose
from operations.contracts import Command, ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.audit.infrastructure.persistence import AuditRepository
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.identity.application.contracts import (
    RequestContext,
    TokenVerifier,
)
from operations.modules.organizations.application.contracts import (
    Organization,
    OrganizationSettings,
)
from operations.modules.workspaces.application.contracts import Workspace

router = APIRouter(prefix="/api/v1", tags=["administration"])
bearer = HTTPBearer(auto_error=False)


def context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> RequestContext:
    try:
        request.app.state.limiter.check(request.client.host if request.client else "unknown")
        if credentials is None:
            raise ServiceError(401, "authentication_required")
        verifier: TokenVerifier = request.app.state.verifier
        principal = verifier.verify(credentials.credentials)
        request.state.principal = principal
        return RequestContext(
            principal,
            UUID(request.state.request_id),
            UUID(request.state.correlation_id),
        )
    except ServiceError as error:
        sessions: sessionmaker[Session] = request.app.state.sessions
        with sessions.begin() as session:
            AuditRepository(session).append(
                AuditEvent(
                    id=uuid7(),
                    type="identity.authentication.failed",
                    occurred_at=datetime.now(UTC),
                    organization_id=None,
                    actor_id=None,
                    correlation_id=UUID(request.state.correlation_id),
                    request_id=UUID(request.state.request_id),
                    aggregate_type="authentication",
                    aggregate_id=None,
                    payload=AuditDetails(reason=error.code),
                )
            )
        raise


Context = Annotated[RequestContext, Depends(context)]


def services(request: Request, actor: Context) -> Iterator[Services]:
    application: Services | None = None
    sessions: sessionmaker[Session] = request.app.state.sessions
    try:
        with sessions.begin() as session:
            application = compose(session, actor.principal, request.app.state.settings)
            selected = request.path_params.get("organization_id")
            if selected is not None:
                try:
                    organization_id = UUID(str(selected))
                except ValueError:
                    organization_id = None
                if organization_id is not None:
                    user = application.identity.store.user(organization_id, actor.principal)
                    if user is not None and user.active:
                        request.state.organization_id = str(organization_id)
                        request.state.actor_id = str(user.id)
            yield application
    except IntegrityError as error:
        if application is not None:
            application.files.compensate_rollback()
        raise ServiceError(409, "conflict") from error
    except BaseException:
        if application is not None:
            application.files.compensate_rollback()
        raise


ServiceDependency = Annotated[Services, Depends(services, scope="function")]


class OrganizationCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    settings: OrganizationSettings = Field(default_factory=OrganizationSettings)
    admin_subject: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr


class OrganizationUpdate(Command):
    name: str = Field(min_length=1, max_length=120)
    settings: OrganizationSettings
    expected_version: int = Field(ge=1)


class WorkspaceCreate(Command):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceUpdate(WorkspaceCreate):
    active: bool = True
    expected_version: int = Field(ge=1)


class Reason(Command):
    reason: str = Field(min_length=1, max_length=500)


class ScopedRole(Command):
    role: Role
    scope_type: ScopeType
    scope_id: UUID


class GrantCreate(ScopedRole):
    user_id: UUID
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class InvitationCreate(ScopedRole):
    email: EmailStr


class InvitationAccept(Command):
    token: str = Field(min_length=40, max_length=100)


class InvitationToken(Command):
    token: str


class VerifiedEmailInvitationCreate(InvitationCreate):
    id: UUID
    email_delivery: bool = False
    email_reason: str | None = Field(default=None, min_length=1, max_length=500)


class InvitationReference(Command):
    id: UUID
    organization_id: UUID
    expires_at: AwareDatetime


class Membership(Command):
    organization_id: UUID
    organization_name: str
    user_id: UUID
    permissions: list[str]


class Me(Command):
    issuer: str
    subject: str
    memberships: list[Membership]


class Identifier(Command):
    id: UUID


class WorkspacePage(Command):
    items: list[Workspace]
    next_cursor: UUID | None


def validated_scope(service: Services, organization_id: UUID, body: ScopedRole) -> Scope:
    service.organizations.active(organization_id)
    if body.scope_type == ScopeType.ORGANIZATION:
        if body.scope_id != organization_id:
            raise ServiceError(403, "access_denied")
    else:
        service.workspaces.active(organization_id, body.scope_id)
    return Scope(organization_id, body.scope_type, body.scope_id)


@router.get("/me", response_model=Me)
def me(actor: Context, service: ServiceDependency) -> Me:
    users = service.identity.store.memberships(actor.principal)
    return Me(
        issuer=actor.principal.issuer,
        subject=actor.principal.subject,
        memberships=[
            Membership(
                organization_id=user.organization_id,
                organization_name=service.organizations.membership_name(
                    actor, user.organization_id
                ),
                user_id=user.id,
                permissions=sorted(
                    service.authorization.allowed(
                        actor,
                        Scope(
                            user.organization_id,
                            ScopeType.ORGANIZATION,
                            user.organization_id,
                        ),
                    )
                ),
            )
            for user in users
        ],
    )


@router.post("/organizations", response_model=Organization, status_code=201)
def create_organization(
    body: OrganizationCreate, actor: Context, service: ServiceDependency
) -> Organization:
    return service.organizations.create(
        actor,
        body.name,
        body.settings,
        body.admin_subject,
        str(body.admin_email),
    )


@router.get("/organizations/{organization_id}", response_model=Organization)
def read_organization(
    organization_id: UUID, actor: Context, service: ServiceDependency
) -> Organization:
    return service.organizations.read(actor, organization_id)


@router.put("/organizations/{organization_id}", response_model=Organization)
def update_organization(
    organization_id: UUID,
    body: OrganizationUpdate,
    actor: Context,
    service: ServiceDependency,
) -> Organization:
    return service.organizations.update(
        actor, organization_id, body.name, body.settings, body.expected_version
    )


@router.post("/organizations/{organization_id}/suspend", status_code=204)
def suspend(
    organization_id: UUID, body: Reason, actor: Context, service: ServiceDependency
) -> None:
    service.organizations.suspend(actor, organization_id, body.reason)


@router.post("/organizations/{organization_id}/resume", status_code=204)
def resume(organization_id: UUID, body: Reason, actor: Context, service: ServiceDependency) -> None:
    service.organizations.resume(actor, organization_id, body.reason)


@router.post(
    "/organizations/{organization_id}/workspaces", response_model=Workspace, status_code=201
)
def create_workspace(
    organization_id: UUID,
    body: WorkspaceCreate,
    actor: Context,
    service: ServiceDependency,
) -> Workspace:
    return service.workspaces.create(actor, organization_id, body.name)


@router.get("/organizations/{organization_id}/workspaces", response_model=WorkspacePage)
def list_workspaces(
    organization_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
) -> WorkspacePage:
    workspaces = service.workspaces.list(actor, organization_id, cursor)
    return WorkspacePage(
        items=workspaces[:100], next_cursor=workspaces[99].id if len(workspaces) > 100 else None
    )


@router.get("/organizations/{organization_id}/workspaces/{workspace_id}", response_model=Workspace)
def read_workspace(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> Workspace:
    return service.workspaces.read(actor, organization_id, workspace_id)


@router.put("/organizations/{organization_id}/workspaces/{workspace_id}", response_model=Workspace)
def update_workspace(
    organization_id: UUID,
    workspace_id: UUID,
    body: WorkspaceUpdate,
    actor: Context,
    service: ServiceDependency,
) -> Workspace:
    return service.workspaces.update(
        actor, organization_id, workspace_id, body.name, body.active, body.expected_version
    )


@router.post("/organizations/{organization_id}/grants", response_model=Identifier, status_code=201)
def create_grant(
    organization_id: UUID,
    body: GrantCreate,
    actor: Context,
    service: ServiceDependency,
) -> Identifier:
    scope = validated_scope(service, organization_id, body)
    target = service.identity.store.by_id(organization_id, body.user_id)
    if target is None or not target.active:
        raise ServiceError(404, "not_found")
    grant = service.authorization.grant(
        actor, target, body.role, scope, body.valid_from, body.valid_until
    )
    return Identifier(id=grant.id)


@router.post("/organizations/{organization_id}/grants/{grant_id}/revoke", status_code=204)
def revoke_grant(
    organization_id: UUID,
    grant_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> None:
    service.organizations.active(organization_id)
    service.authorization.revoke(actor, organization_id, grant_id)


@router.post(
    "/organizations/{organization_id}/invitations", response_model=InvitationToken, status_code=201
)
def invite(
    organization_id: UUID,
    body: InvitationCreate,
    actor: Context,
    service: ServiceDependency,
) -> InvitationToken:
    scope = validated_scope(service, organization_id, body)
    return InvitationToken(token=service.identity.invite(actor, str(body.email), body.role, scope))


@router.post("/organizations/{organization_id}/invitations/accept", response_model=Identifier)
def accept(
    organization_id: UUID,
    body: InvitationAccept,
    actor: Context,
    service: ServiceDependency,
) -> Identifier:
    return Identifier(id=service.identity.accept(actor, organization_id, body.token).id)


@router.post(
    "/organizations/{organization_id}/invitations/verified-email",
    response_model=InvitationReference,
    status_code=201,
)
def invite_verified_email(
    organization_id: UUID,
    body: VerifiedEmailInvitationCreate,
    actor: Context,
    service: ServiceDependency,
) -> InvitationReference:
    scope = validated_scope(service, organization_id, body)
    invitation = service.email.invite(
        actor, str(body.email), body.role, scope, body.id, body.email_delivery, body.email_reason
    )
    return InvitationReference(
        id=invitation.id,
        organization_id=invitation.organization_id,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/organizations/{organization_id}/invitations/verified-email/{invitation_id}/accept",
    response_model=Identifier,
)
def accept_verified_email(
    organization_id: UUID,
    invitation_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> Identifier:
    return Identifier(
        id=service.identity.accept_verified_email(actor, organization_id, invitation_id).id
    )


@router.post("/organizations/{organization_id}/users/{user_id}/revoke", status_code=204)
def revoke_user(
    organization_id: UUID,
    user_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> None:
    service.identity.revoke(actor, organization_id, user_id)
