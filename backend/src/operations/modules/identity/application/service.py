import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import (
    IdentityStore,
    Invitation,
    Principal,
    RequestContext,
    User,
)
from operations.modules.organizations.application.contracts import OrganizationReader


class IdentityService:
    def __init__(
        self,
        store: IdentityStore,
        organizations: OrganizationReader,
        authorization: Authorization,
        audit: AuditWriter,
    ) -> None:
        self.store, self.organizations, self.authorization, self.audit = (
            store,
            organizations,
            authorization,
            audit,
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

    def accept(self, context: RequestContext, organization_id: UUID, token: str) -> User:
        self.organizations.active(organization_id)
        invitation = self.store.invitation(
            organization_id,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        principal = context.principal
        now = datetime.now(UTC)
        if (
            invitation is None
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
