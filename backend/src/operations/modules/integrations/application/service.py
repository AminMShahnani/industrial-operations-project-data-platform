"""Scoped webhook endpoint lifecycle; secret material stays in external storage."""

from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.forms.application.service import FormService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.integrations.application.contracts import (
    EndpointCreate,
    EndpointRevise,
    EndpointStore,
    EndpointVersion,
)
from operations.modules.integrations.application.webhooks import validate_endpoint_url


class WebhookEndpointService:
    def __init__(self, store: EndpointStore, forms: FormService, audit: AuditWriter) -> None:
        self.store, self.forms, self.audit = store, forms, audit

    def require(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
    ) -> UUID:
        if (workspace_id is None) != (project_id is None) and project_id is not None:
            raise ServiceError(422, "webhook_endpoint_project_requires_workspace")
        if workspace_id is None:
            scope = Scope(organization_id, ScopeType.ORGANIZATION, organization_id)
            return self.forms.authorization.require(actor, "integration.manage", scope).id
        self.forms.require(
            actor, organization_id, workspace_id, project_id, "integration.manage", True
        )
        return self.forms.authorization.user(actor, organization_id).id

    def audit_event(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        endpoint_id: UUID,
        audit_id: UUID,
        version: int,
        action: str,
        occurred_at: datetime,
        reason: str | None = None,
    ) -> None:
        user = self.forms.authorization.user(actor, organization_id)
        self.audit.append(
            AuditEvent(
                id=audit_id,
                type="integration.webhook_endpoint." + action,
                occurred_at=occurred_at,
                organization_id=organization_id,
                actor_id=user.id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="webhook_endpoint",
                aggregate_id=endpoint_id,
                payload=AuditDetails(
                    reason=reason,
                    target_id=endpoint_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    version=version,
                    scope_type="organization" if workspace_id is None else "workspace",
                    scope_id=organization_id if workspace_id is None else workspace_id,
                ),
            )
        )

    def create(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        command: EndpointCreate,
    ) -> EndpointVersion:
        user_id = self.require(actor, organization_id, workspace_id, project_id)
        validate_endpoint_url(command.url)
        endpoint_id, audit_id = uuid7(), uuid7()
        now = datetime.now(UTC)
        row = EndpointVersion(
            audit_id=audit_id,
            endpoint_id=endpoint_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            version=1,
            name=command.name.strip(),
            url=command.url,
            secret_reference=command.secret_reference,
            created_by_id=user_id,
            created_at=now,
        )
        self.audit_event(
            actor,
            organization_id,
            workspace_id,
            project_id,
            endpoint_id,
            audit_id,
            1,
            "created",
            now,
        )
        self.store.add(row)
        return row

    def page(
        self,
        actor: RequestContext,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        after: UUID | None = None,
    ) -> list[EndpointVersion]:
        self.require(actor, organization_id, workspace_id, project_id)
        return self.store.page(organization_id, workspace_id, project_id, after)

    def version(
        self,
        actor: RequestContext,
        organization_id: UUID,
        endpoint_id: UUID,
        number: int,
    ) -> EndpointVersion:
        row = self.store.version(organization_id, endpoint_id, number)
        if row is None:
            raise ServiceError(404, "webhook_endpoint_not_found")
        self.require(actor, organization_id, row.workspace_id, row.project_id)
        return row

    def revise(
        self,
        actor: RequestContext,
        organization_id: UUID,
        endpoint_id: UUID,
        command: EndpointRevise,
    ) -> EndpointVersion:
        latest = self.store.latest(organization_id, endpoint_id)
        if latest is None:
            raise ServiceError(404, "webhook_endpoint_not_found")
        user_id = self.require(actor, organization_id, latest.workspace_id, latest.project_id)
        if latest.version != command.expected_version:
            raise ServiceError(409, "webhook_endpoint_version_conflict")
        if latest.state != "active":
            raise ServiceError(409, "webhook_endpoint_revoked")
        validate_endpoint_url(command.url)
        return self._append(
            actor,
            latest,
            user_id,
            latest.version + 1,
            command.name.strip(),
            command.url,
            command.secret_reference,
            "versioned",
        )

    def revoke(
        self,
        actor: RequestContext,
        organization_id: UUID,
        endpoint_id: UUID,
        expected_version: int,
        reason: str,
    ) -> EndpointVersion:
        latest = self.store.latest(organization_id, endpoint_id)
        if latest is None:
            raise ServiceError(404, "webhook_endpoint_not_found")
        user_id = self.require(actor, organization_id, latest.workspace_id, latest.project_id)
        if latest.version != expected_version:
            raise ServiceError(409, "webhook_endpoint_version_conflict")
        if latest.state == "revoked":
            raise ServiceError(409, "webhook_endpoint_revoked")
        return self._append(
            actor,
            latest,
            user_id,
            latest.version + 1,
            latest.name,
            latest.url,
            latest.secret_reference,
            "revoked",
            reason.strip(),
        )

    def _append(
        self,
        actor: RequestContext,
        latest: EndpointVersion,
        user_id: UUID,
        version: int,
        name: str,
        url: str,
        secret_reference: str,
        action: str,
        reason: str | None = None,
    ) -> EndpointVersion:
        audit_id = uuid7()
        now = datetime.now(UTC)
        row = latest.model_copy(
            update={
                "audit_id": audit_id,
                "version": version,
                "name": name,
                "url": url,
                "secret_reference": secret_reference,
                "state": "revoked" if action == "revoked" else "active",
                "created_by_id": user_id,
                "created_at": now,
            }
        )
        self.audit_event(
            actor,
            row.organization_id,
            row.workspace_id,
            row.project_id,
            row.endpoint_id,
            audit_id,
            version,
            action,
            now,
            reason,
        )
        self.store.add(row)
        return row
