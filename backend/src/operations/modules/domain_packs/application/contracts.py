"""Application contracts for organization-scoped Domain Pack lifecycle."""

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import Field, StrictStr

from operations.contracts import Command
from operations.modules.audit.application.contracts import AuditWriter
from operations.modules.domain_packs.application.dependency_resolution import PackRelease
from operations.modules.domain_packs.application.manifest import PackContentChecksum
from operations.modules.domain_packs.application.migrations import MigrationOperation
from operations.modules.domain_packs.application.registry import RegistrySnapshot
from operations.modules.iam.application.contracts import Scope
from operations.modules.identity.application.contracts import RequestContext, User


class InstallationState(StrEnum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


class LifecycleOperation(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    ENABLE = "enable"
    DISABLE = "disable"
    UNINSTALL = "uninstall"


class PlanStepAction(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    ENABLE = "enable"
    DISABLE = "disable"
    UNINSTALL = "uninstall"
    NOOP = "noop"


class PackInstallation(Command):
    id: UUID
    organization_id: UUID
    pack_id: str
    version: str
    content_sha256: str
    state: InstallationState
    row_version: int
    created_at: datetime
    updated_at: datetime
    installed_by: UUID


class PackArtifactImport(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    idempotency_key: UUID
    pack_id: str
    pack_version: str
    package_sha256: str
    artifact_id: str
    artifact_version: int
    artifact_kind: str
    target_id: UUID
    imported_by: UUID
    created_at: datetime


class InstallationPage(Command):
    items: list[PackInstallation]


class LifecyclePlanRequest(Command):
    operation: LifecycleOperation
    pack_id: str = Field(min_length=3, max_length=180)
    version_range: str | None = Field(default=None, min_length=1, max_length=128)


class LifecyclePlanStep(Command):
    pack_id: str
    action: PlanStepAction
    from_version: str | None = None
    to_version: str | None = None
    content_sha256: str | None = None
    expected_row_version: int | None = None
    requires_breaking_review: bool = False


class LifecyclePlanIssue(Command):
    code: str
    pack_id: str
    message: str


class PackReleaseSummary(Command):
    pack_id: str
    version: str
    content_sha256: str
    registry_locator: str
    migration_operations: list[MigrationOperation] = Field(default_factory=list)


class LifecyclePlan(Command):
    organization_id: UUID
    operation: LifecycleOperation
    pack_id: str
    valid: bool
    plan_sha256: str | None = None
    selected_releases: list[PackRelease] = Field(default_factory=list)
    selected_release_summaries: list[PackReleaseSummary] = Field(default_factory=list)
    steps: list[LifecyclePlanStep] = Field(default_factory=list)
    issues: list[LifecyclePlanIssue] = Field(default_factory=list)

    def public(self) -> LifecyclePlan:
        selected = [
            PackReleaseSummary(
                pack_id=release.manifest.id,
                version=release.manifest.version,
                content_sha256=release.content_sha256,
                registry_locator=release.registry_locator,
                migration_operations=release.migration_operations,
            )
            for release in self.selected_releases
        ]
        return self.model_copy(
            update={"selected_releases": [], "selected_release_summaries": selected}
        )


class LifecycleApplyRequest(Command):
    operation: LifecycleOperation
    pack_id: str = Field(min_length=3, max_length=180)
    version_range: str | None = Field(default=None, min_length=1, max_length=128)
    expected_plan_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    reason: StrictStr = Field(min_length=1, max_length=500)
    confirm_breaking_change: bool = False


class PackRegistry(Protocol):
    def snapshot(self) -> RegistrySnapshot: ...


class PackRegistryProvider(Protocol):
    def snapshot(self) -> RegistrySnapshot: ...


class PackInstallationStore(Protocol):
    def get(self, organization_id: UUID, pack_id: str) -> PackInstallation | None: ...
    def installations(self, organization_id: UUID) -> list[PackInstallation]: ...
    def create(self, installation: PackInstallation) -> None: ...
    def update(self, installation: PackInstallation, expected_row_version: int) -> bool: ...
    def add_provenance(
        self,
        organization_id: UUID,
        installation_id: UUID,
        pack_id: str,
        version: str,
        package_sha256: str,
        artifacts: list[PackContentChecksum],
    ) -> None: ...
    def registry_release(self, pack_id: str, version: str) -> PackRelease | None: ...
    def has_materialized_artifacts(self, organization_id: UUID, pack_id: str) -> bool: ...


class PackArtifactImportStore(Protocol):
    def get_by_key(self, organization_id: UUID, key: UUID) -> PackArtifactImport | None: ...
    def get_source(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID | None,
        pack_id: str,
        pack_version: str,
        artifact_id: str,
        artifact_version: int,
    ) -> PackArtifactImport | None: ...
    def create(self, result: PackArtifactImport) -> None: ...


class AuthorizationService(Protocol):
    def require(self, context: RequestContext, permission: str, scope: Scope) -> User: ...


class OrganizationLifecycle(Protocol):
    def active(self, organization_id: UUID) -> object: ...
    def lock(self, organization_id: UUID) -> None: ...


class AuditAppender(AuditWriter, Protocol):
    pass
