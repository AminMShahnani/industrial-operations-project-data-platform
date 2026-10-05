from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.organizations.application.contracts import OrganizationReader
from operations.modules.workspaces.application.contracts import (
    ProjectVisibility,
    Workspace,
    WorkspaceStore,
)


class WorkspaceService:
    def __init__(
        self,
        store: WorkspaceStore,
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
        self.project_visibility: ProjectVisibility | None = None

    def active(self, organization_id: UUID, workspace_id: UUID) -> Workspace:
        self.organizations.active(organization_id)
        workspace = self.store.get(organization_id, workspace_id)
        if workspace is None or not workspace.active:
            raise ServiceError(404, "not_found")
        return workspace

    def read(self, context: RequestContext, organization_id: UUID, workspace_id: UUID) -> Workspace:
        allowed = self.authorization.allowed(
            context, Scope(organization_id, ScopeType.WORKSPACE, workspace_id)
        )
        if "workspace.read" not in allowed and (
            self.project_visibility is None
            or workspace_id not in self.project_visibility.workspace_ids(context, organization_id)
        ):
            raise ServiceError(403, "access_denied")
        return self.active(organization_id, workspace_id)

    def create(self, context: RequestContext, organization_id: UUID, name: str) -> Workspace:
        self.organizations.active(organization_id)
        actor = self.authorization.require(
            context,
            "workspace.create",
            Scope(
                organization_id,
                ScopeType.ORGANIZATION,
                organization_id,
            ),
        )
        workspace = Workspace(uuid7(), organization_id, name, True, 1)
        self.store.create(workspace)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="workspace.created",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="workspace",
                aggregate_id=workspace.id,
            )
        )
        return workspace

    def update(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        name: str,
        active: bool,
        expected_version: int,
    ) -> Workspace:
        actor = self.authorization.require(
            context,
            "workspace.manage",
            Scope(
                organization_id,
                ScopeType.WORKSPACE,
                workspace_id,
            ),
        )
        self.organizations.active(organization_id)
        workspace = self.store.get(organization_id, workspace_id)
        if workspace is None:
            raise ServiceError(404, "not_found")
        changed = replace(workspace, name=name, active=active, version=expected_version + 1)
        if not self.store.update(changed, expected_version):
            raise ServiceError(409, "version_conflict")
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="workspace.updated",
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor_id=actor.id,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                aggregate_type="workspace",
                aggregate_id=workspace_id,
                payload=AuditDetails(version=changed.version),
            )
        )
        return changed

    def list(
        self,
        context: RequestContext,
        organization_id: UUID,
        after: UUID | None,
    ) -> list[Workspace]:
        self.organizations.active(organization_id)
        visible = self.authorization.workspace_filter(context, organization_id)
        if visible is not None and self.project_visibility is not None:
            visible = list(
                set(visible) | set(self.project_visibility.workspace_ids(context, organization_id))
            )
        return self.store.list(organization_id, visible, after)
