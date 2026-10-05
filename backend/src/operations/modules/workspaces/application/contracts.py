from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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
