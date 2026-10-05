from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Grant, GrantStore, Role, Scope, ScopeType
from operations.modules.iam.domain.policy import permissions, role_permissions
from operations.modules.identity.application.contracts import IdentityStore, RequestContext, User


class Authorization:
    def __init__(self, identities: IdentityStore, grants: GrantStore, audit: AuditWriter) -> None:
        self.identities, self.grants, self.audit = identities, grants, audit

    def user(self, context: RequestContext, organization_id: UUID) -> User:
        user = self.identities.user(organization_id, context.principal)
        if user is None or not user.active:
            raise ServiceError(403, "access_denied")
        return user

    def allowed(self, context: RequestContext, scope: Scope) -> frozenset[str]:
        user = self.user(context, scope.organization_id)
        return permissions(
            self.grants.for_user(scope.organization_id, user.id), user.id, scope, datetime.now(UTC)
        )

    def require(self, context: RequestContext, permission: str, scope: Scope) -> User:
        if permission not in self.allowed(context, scope):
            raise ServiceError(403, "access_denied")
        return self.user(context, scope.organization_id)

    def check_delegation(self, context: RequestContext, role: Role, scope: Scope) -> User:
        actor = self.require(context, "iam.grants.manage", scope)
        if not role_permissions(role, scope.type) <= self.allowed(context, scope):
            raise ServiceError(403, "privilege_escalation")
        if role == Role.ORGANIZATION_ADMIN and scope.type != ScopeType.ORGANIZATION:
            raise ServiceError(422, "invalid_role_scope")
        if (
            role in {Role.WORKSPACE_ADMIN, Role.WORKSPACE_OWNER}
            and scope.type != ScopeType.WORKSPACE
        ):
            raise ServiceError(422, "invalid_role_scope")
        return actor

    def grant(
        self,
        context: RequestContext,
        target: User,
        role: Role,
        scope: Scope,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        audit_actor_id: UUID | None = None,
    ) -> Grant:
        actor = self.check_delegation(context, role, scope)
        if target.organization_id != scope.organization_id or target.id == actor.id:
            raise ServiceError(403, "privilege_escalation")
        if valid_from and valid_until and valid_until <= valid_from:
            raise ServiceError(422, "invalid_validity_window")
        grant = Grant(
            uuid7(),
            scope.organization_id,
            target.id,
            role,
            scope.type,
            scope.id,
            role == Role.ORGANIZATION_ADMIN,
            valid_from,
            valid_until,
        )
        self.grants.create(grant)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="iam.grant.created",
                occurred_at=datetime.now(UTC),
                organization_id=scope.organization_id,
                actor_id=audit_actor_id or actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="grant",
                aggregate_id=grant.id,
                payload=AuditDetails(
                    target_id=target.id,
                    role=role,
                    scope_type=scope.type,
                    scope_id=scope.id,
                    authorized_by=actor.id if audit_actor_id else None,
                ),
            )
        )
        return grant

    def revoke(self, context: RequestContext, organization_id: UUID, grant_id: UUID) -> None:
        grant = self.grants.get(organization_id, grant_id)
        if grant is None:
            raise ServiceError(404, "not_found")
        scope = Scope(organization_id, grant.scope_type, grant.scope_id)
        actor = self.check_delegation(context, grant.role, scope)
        if actor.id == grant.user_id:
            raise ServiceError(403, "privilege_escalation")
        self.grants.revoke(organization_id, grant_id)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="iam.grant.revoked",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="grant",
                aggregate_id=grant.id,
            )
        )

    def workspace_filter(self, context: RequestContext, organization_id: UUID) -> list[UUID] | None:
        user = self.user(context, organization_id)
        grants = self.grants.for_user(organization_id, user.id)
        now = datetime.now(UTC)
        visible: set[UUID] = set()
        for grant in grants:
            if grant.scope_type == ScopeType.ORGANIZATION and grant.inherit:
                scope = Scope(organization_id, ScopeType.WORKSPACE, organization_id)
                if "workspace.read" in permissions([grant], user.id, scope, now):
                    return None
            elif grant.scope_type == ScopeType.WORKSPACE:
                scope = Scope(organization_id, ScopeType.WORKSPACE, grant.scope_id)
                if "workspace.read" in permissions([grant], user.id, scope, now):
                    visible.add(grant.scope_id)
        return list(visible)
