from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Grant, GrantStore, Role, Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import IdentityStore, RequestContext, User
from operations.modules.organizations.application.contracts import (
    Organization,
    OrganizationSettings,
    OrganizationStore,
)


class OrganizationService:
    def __init__(
        self,
        store: OrganizationStore,
        identities: IdentityStore,
        grants: GrantStore,
        authorization: Authorization,
        audit: AuditWriter,
    ) -> None:
        self.store, self.identities, self.grants = store, identities, grants
        self.authorization, self.audit = authorization, audit

    def active(self, organization_id: UUID) -> Organization:
        organization = self.store.get(organization_id)
        if organization is None:
            raise ServiceError(404, "not_found")
        if not organization.active:
            raise ServiceError(403, "organization_suspended")
        return organization

    def read(self, context: RequestContext, organization_id: UUID) -> Organization:
        self.authorization.require(
            context,
            "organization.read",
            Scope(
                organization_id,
                ScopeType.ORGANIZATION,
                organization_id,
            ),
        )
        return self.active(organization_id)

    def membership_name(self, context: RequestContext, organization_id: UUID) -> str:
        self.authorization.user(context, organization_id)
        organization = self.store.get(organization_id)
        if organization is None:
            raise ServiceError(404, "not_found")
        return organization.name

    def create(
        self,
        context: RequestContext,
        name: str,
        settings: OrganizationSettings,
        admin_subject: str,
        admin_email: str,
    ) -> Organization:
        if not self.identities.platform_admin(context.principal):
            raise ServiceError(403, "access_denied")
        organization = Organization(uuid7(), name, settings, True, 1)
        self.store.create(organization)
        user = User(
            uuid7(),
            organization.id,
            context.principal.issuer,
            admin_subject,
            admin_email.casefold(),
            True,
        )
        self.identities.create_user(user)
        grant = Grant(
            uuid7(),
            organization.id,
            user.id,
            Role.ORGANIZATION_ADMIN,
            ScopeType.ORGANIZATION,
            organization.id,
            True,
        )
        self.grants.create(grant)
        for action, aggregate, identifier in (
            ("organization.created", "organization", organization.id),
            ("identity.user.created", "user", user.id),
            ("iam.grant.created", "grant", grant.id),
        ):
            self.audit.append(
                AuditEvent(
                    id=uuid7(),
                    type=action,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization.id,
                    actor_id=None,
                    correlation_id=context.correlation_id,
                    request_id=context.request_id,
                    aggregate_type=aggregate,
                    aggregate_id=identifier,
                    payload=AuditDetails(target_id=user.id, role=Role.ORGANIZATION_ADMIN),
                )
            )
        return organization

    def update(
        self,
        context: RequestContext,
        organization_id: UUID,
        name: str,
        settings: OrganizationSettings,
        expected_version: int,
    ) -> Organization:
        actor = self.authorization.require(
            context,
            "organization.manage",
            Scope(
                organization_id,
                ScopeType.ORGANIZATION,
                organization_id,
            ),
        )
        organization = self.active(organization_id)
        changed = replace(organization, name=name, settings=settings, version=expected_version + 1)
        if not self.store.update(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="organization.updated",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="organization",
                aggregate_id=organization_id,
                payload=AuditDetails(version=changed.version),
            )
        )
        return changed

    def suspend(self, context: RequestContext, organization_id: UUID, reason: str) -> None:
        if not self.identities.platform_admin(context.principal):
            raise ServiceError(403, "access_denied")
        organization = self.active(organization_id)
        changed = replace(organization, active=False, version=organization.version + 1)
        if not self.store.update(changed, organization.version):
            raise ServiceError(409, "version_conflict")
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="organization.suspended",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=None,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="organization",
                aggregate_id=organization_id,
                payload=AuditDetails(reason=reason),
            )
        )

    def resume(self, context: RequestContext, organization_id: UUID, reason: str) -> None:
        if not self.identities.platform_admin(context.principal):
            raise ServiceError(403, "access_denied")
        organization = self.store.get(organization_id)
        if organization is None:
            raise ServiceError(404, "not_found")
        if organization.active:
            return
        changed = replace(organization, active=True, version=organization.version + 1)
        if not self.store.update(changed, organization.version):
            raise ServiceError(409, "version_conflict")
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="organization.resumed",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=None,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="organization",
                aggregate_id=organization_id,
                payload=AuditDetails(reason=reason),
            )
        )
