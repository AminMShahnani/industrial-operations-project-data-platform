from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.projects.domain.lifecycle import Lifecycle


class LifecycleDefinition(Command):
    version: int = Field(default=1, ge=1)
    states: tuple[str, ...] = Lifecycle().states
    transitions: tuple[tuple[str, str], ...] = Lifecycle().transitions
    initial: str = "planned"
    terminal: tuple[str, ...] = ("archived",)

    def policy(self) -> Lifecycle:
        return Lifecycle(self.states, self.transitions, self.initial, self.terminal)

    @model_validator(mode="after")
    def controlled_graph(self) -> LifecycleDefinition:
        if not self.policy().valid() or any(
            not state.isascii() or not state.replace("_", "").isalnum() or len(state) > 40
            for state in self.states
        ):
            raise ValueError("Invalid controlled lifecycle graph")
        return self


class ProjectContext(Command):
    description: str = Field(default="", max_length=2000)
    starts_on: date | None = None
    ends_on: date | None = None
    location_ids: list[UUID] = Field(default_factory=list, max_length=100)
    asset_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def dates(self) -> ProjectContext:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("End date must not precede start date")
        return self


class Project(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    state: str
    lifecycle: LifecycleDefinition
    context: ProjectContext
    version: int


class ProjectRole(StrEnum):
    MANAGER = "ProjectManager"
    VIEWER = "Viewer"
    CONTRIBUTOR = "Contributor"


class ProjectMembership(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    revoked: bool = False


class DepartmentProjectGrant(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID
    department_id: UUID
    role: ProjectRole
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    revoked: bool = False


class ProjectStore(Protocol):
    def add_milestone(self, row: Milestone) -> None: ...
    def milestone(
        self, org: UUID, workspace: UUID, project: UUID, identifier: UUID
    ) -> Milestone | None: ...
    def get(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID
    ) -> Project | None: ...
    def create(self, project: Project) -> None: ...
    def update(self, project: Project, expected_version: int) -> bool: ...
    def list_projects(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        visible: list[UUID] | None,
        after: UUID | None,
    ) -> list[Project]: ...
    def memberships(self, organization_id: UUID, user_id: UUID) -> list[ProjectMembership]: ...
    def add_membership(self, membership: ProjectMembership) -> None: ...
    def membership(
        self, organization_id: UUID, project_id: UUID, membership_id: UUID
    ) -> ProjectMembership | None: ...
    def revoke_membership(self, organization_id: UUID, membership_id: UUID) -> None: ...
    def department_grants(
        self, organization_id: UUID, department_ids: list[UUID]
    ) -> list[DepartmentProjectGrant]: ...
    def add_department_grant(self, grant: DepartmentProjectGrant) -> None: ...
    def department_grant(
        self, organization_id: UUID, project_id: UUID, grant_id: UUID
    ) -> DepartmentProjectGrant | None: ...
    def revoke_department_grant(self, organization_id: UUID, grant_id: UUID) -> None: ...


class Milestone(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID
    name: str = Field(min_length=1, max_length=120)
    planned_at: datetime

    @model_validator(mode="after")
    def aware(self) -> Milestone:
        if self.planned_at.tzinfo is None:
            raise ValueError("Aware milestone timestamp required")
        return self
