import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import (
    AccessRevoker,
    IdentityStore,
    Invitation,
    Principal,
    RequestContext,
    User,
)
from operations.modules.organizations.application.contracts import OrganizationReader
from operations.modules.workspaces.application.contracts import WorkspaceReader


class IdentityService:
    def __init__(
        self,
        store: IdentityStore,
        organizations: OrganizationReader,
        authorization: Authorization,
        audit: AuditWriter,
        workspaces: WorkspaceReader,
        revokers: list[AccessRevoker] | None = None,
    ) -> None:
        self.store, self.organizations, self.authorization, self.audit = (
            store,
            organizations,
            authorization,
            audit,
        )
        self.revokers = revokers or []
        self.workspaces = workspaces

    def active_context(
        self, organization_id: UUID, identifier: UUID, source: RequestContext
    ) -> RequestContext:
        """Trusted application handoff; resolve a current tenant membership, never a token."""
        self.organizations.active(organization_id)
        user = self.store.by_id(organization_id, identifier)
        if user is None or not user.active:
            raise ServiceError(403, "notification_recipient_unavailable")
        return RequestContext(
            Principal(user.issuer, user.subject), source.request_id, source.correlation_id
        )

    def bootstrap(self, principal: Principal, reason: str) -> None:
        self.store.bootstrap(principal)
        event_id = uuid7()
        self.audit.append(
            AuditEvent(
                id=event_id,
                type="identity.platform_admin.bootstrapped",
                occurred_at=datetime.now(UTC),
                organization_id=None,
                actor_id=None,
                correlation_id=event_id,
                request_id=event_id,
                aggregate_type="platform_admin",
                aggregate_id=None,
                payload=AuditDetails(reason=reason),
            )
        )

    def invite(self, context: RequestContext, email: str, role: Role, scope: Scope) -> str:
        self.organizations.active(scope.organization_id)
        actor = self.authorization.check_delegation(context, role, scope)
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            uuid7(),
            scope.organization_id,
            email.casefold(),
            hashlib.sha256(token.encode()).hexdigest(),
            role,
            scope.id,
            scope.type,
            actor.id,
            datetime.now(UTC) + timedelta(days=7),
            None,
        )
        self.store.invite(invitation)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="identity.invitation.created",
                occurred_at=datetime.now(UTC),
                organization_id=scope.organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="invitation",
                aggregate_id=invitation.id,
                payload=AuditDetails(role=role, scope_id=scope.id, scope_type=scope.type),
            )
        )
        return token

    def invite_verified_email(
        self, context: RequestContext, email: str, role: Role, scope: Scope, identifier: UUID
    ) -> Invitation:
        self.organizations.active(scope.organization_id)
        actor = self.authorization.check_delegation(context, role, scope)
        self._active_scope(scope)
        if identifier.version != 7:
            raise ServiceError(422, "invalid_invitation_id")
        normalized = email.casefold()
        existing = self.store.invitation_by_id(scope.organization_id, identifier)
        if existing is not None:
            if (
                existing.acceptance_mode != "verified_email"
                or existing.email != normalized
                or existing.role != role
                or existing.scope_id != scope.id
                or existing.scope_type != scope.type
                or existing.inviter_id != actor.id
            ):
                raise ServiceError(409, "invitation_request_conflict")
            return existing
        invitation = Invitation(
            identifier,
            scope.organization_id,
            normalized,
            None,
            role,
            scope.id,
            scope.type,
            actor.id,
            datetime.now(UTC) + timedelta(days=7),
            None,
            "verified_email",
        )
        self.store.invite(invitation)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="identity.invitation.email_created",
                occurred_at=datetime.now(UTC),
                organization_id=scope.organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="invitation",
                aggregate_id=invitation.id,
                payload=AuditDetails(role=role, scope_id=scope.id, scope_type=scope.type),
            )
        )
        return invitation

    def _active_scope(self, scope: Scope) -> None:
        if scope.type == ScopeType.WORKSPACE:
            self.workspaces.active(scope.organization_id, scope.id)
        elif scope.type != ScopeType.ORGANIZATION or scope.id != scope.organization_id:
            raise ServiceError(403, "invalid_invitation")

    def accept_verified_email(
        self, context: RequestContext, organization_id: UUID, identifier: UUID
    ) -> User:
        self.organizations.active(organization_id)
        invitation = self.store.invitation_by_id(organization_id, identifier)
        if invitation is None or invitation.acceptance_mode != "verified_email":
            raise ServiceError(403, "invalid_invitation")
        return self._accept_invitation(context, organization_id, invitation)

    def accept(self, context: RequestContext, organization_id: UUID, token: str) -> User:
        self.organizations.active(organization_id)
        invitation = self.store.invitation(
            organization_id,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        if invitation is None or invitation.acceptance_mode != "token":
            raise ServiceError(403, "invalid_invitation")
        return self._accept_invitation(context, organization_id, invitation)

    def _accept_invitation(
        self, context: RequestContext, organization_id: UUID, invitation: Invitation
    ) -> User:
        principal = context.principal
        now = datetime.now(UTC)
        if (
            invitation.organization_id != organization_id
            or invitation.accepted_at is not None
            or now >= invitation.expires_at
            or not principal.email_verified
            or principal.email is None
            or principal.email.casefold() != invitation.email
        ):
            raise ServiceError(403, "invalid_invitation")
        inviter = self.store.by_id(organization_id, invitation.inviter_id)
        if inviter is None or not inviter.active:
            raise ServiceError(403, "invalid_invitation")
        inviter_context = RequestContext(
            Principal(inviter.issuer, inviter.subject),
            context.request_id,
            context.correlation_id,
        )
        scope = Scope(organization_id, ScopeType(invitation.scope_type), invitation.scope_id)
        if invitation.acceptance_mode == "verified_email":
            self._active_scope(scope)
        role = Role(invitation.role)
        self.authorization.check_delegation(inviter_context, role, scope)
        user = self.store.user(organization_id, principal)
        if user is None:
            user = User(
                uuid7(),
                organization_id,
                principal.issuer,
                principal.subject,
                invitation.email,
                True,
            )
            self.store.create_user(user)
        elif not user.active:
            self.store.set_active(organization_id, user.id, True)
            user = User(user.id, organization_id, user.issuer, user.subject, user.email, True)
        self.authorization.grant(inviter_context, user, role, scope, audit_actor_id=user.id)
        self.store.accept(organization_id, invitation.id, now)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="identity.invitation.accepted",
                occurred_at=now,
                organization_id=organization_id,
                actor_id=user.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="invitation",
                aggregate_id=invitation.id,
                payload=AuditDetails(target_id=user.id),
            )
        )
        return user

    def revoke(self, context: RequestContext, organization_id: UUID, user_id: UUID) -> None:
        self.organizations.active(organization_id)
        actor = self.authorization.require(
            context,
            "organization.members.manage",
            Scope(
                organization_id,
                ScopeType.ORGANIZATION,
                organization_id,
            ),
        )
        if actor.id == user_id:
            raise ServiceError(403, "privilege_escalation")
        target = self.store.by_id(organization_id, user_id)
        if target is None:
            raise ServiceError(404, "not_found")
        self.store.set_active(organization_id, user_id, False)
        for grant in self.authorization.grants.for_user(organization_id, user_id):
            if not grant.revoked:
                self.authorization.revoke(context, organization_id, grant.id)
        for revoker in self.revokers:
            revoker.revoke_user_access(context, organization_id, user_id)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="identity.user.revoked",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="user",
                aggregate_id=user_id,
            )
        )
