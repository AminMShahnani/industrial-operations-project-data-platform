from enum import StrEnum
from typing import Protocol
from uuid import UUID

from operations.contracts import Command


class GroupKind(StrEnum):
    DEPARTMENT = "department"
    TEAM = "team"


class Group(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    kind: GroupKind
    name: str
    active: bool = True
    version: int = 1


class GroupMembership(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    group_id: UUID
    user_id: UUID
    manager: bool = False
    active: bool = True


class GroupReader(Protocol):
    def active_department(
        self, organization_id: UUID, workspace_id: UUID, group_id: UUID
    ) -> Group: ...
    def departments_for_user(
        self, organization_id: UUID, workspace_id: UUID, user_id: UUID
    ) -> list[UUID]: ...
    def department_workspaces(
        self, organization_id: UUID, user_id: UUID
    ) -> dict[UUID, list[UUID]]: ...
    def workspace_ids(self, organization_id: UUID, user_id: UUID) -> list[UUID]: ...


class GroupStore(Protocol):
    def get(self, organization_id: UUID, workspace_id: UUID, group_id: UUID) -> Group | None: ...
    def create(self, group: Group) -> None: ...
    def update(self, group: Group, expected_version: int) -> bool: ...
    def list_groups(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        after: UUID | None,
        visible: list[UUID] | None = None,
    ) -> list[Group]: ...
    def membership(
        self, organization_id: UUID, group_id: UUID, membership_id: UUID
    ) -> GroupMembership | None: ...
    def add_membership(self, membership: GroupMembership) -> None: ...
    def revoke(self, organization_id: UUID, membership_id: UUID) -> None: ...
    def memberships(
        self, organization_id: UUID, workspace_id: UUID, user_id: UUID
    ) -> list[GroupMembership]: ...
    def active_memberships_for_user(
        self, organization_id: UUID, user_id: UUID
    ) -> list[GroupMembership]: ...
