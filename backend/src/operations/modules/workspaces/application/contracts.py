from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from operations.modules.identity.application.contracts import RequestContext


@dataclass(frozen=True)
class Workspace:
    id: UUID
    organization_id: UUID
    name: str
    active: bool
    version: int


class WorkspaceStore(Protocol):
    def get(self, organization_id: UUID, workspace_id: UUID) -> Workspace | None: ...
    def create(self, workspace: Workspace) -> None: ...
    def update(self, workspace: Workspace, expected_version: int) -> bool: ...
    def list(
        self,
        organization_id: UUID,
        workspace_ids: list[UUID] | None,
        after: UUID | None,
    ) -> list[Workspace]: ...


class WorkspaceReader(Protocol):
    def active(self, organization_id: UUID, workspace_id: UUID) -> Workspace: ...


class ProjectVisibility(Protocol):
    def workspace_ids(self, context: RequestContext, organization_id: UUID) -> list[UUID]: ...
