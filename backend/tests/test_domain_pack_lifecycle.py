from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditEvent
from operations.modules.domain_packs.application.contracts import (
    InstallationState,
    LifecycleApplyRequest,
    LifecycleOperation,
    LifecyclePlanRequest,
    PackInstallation,
)
from operations.modules.domain_packs.application.dependency_resolution import PackRelease
from operations.modules.domain_packs.application.manifest import (
    PackCapability,
    PackContentChecksum,
    PackManifest,
    PackType,
)
from operations.modules.domain_packs.application.registry import RegistrySnapshot
from operations.modules.domain_packs.application.service import DomainPackService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import (
    Principal,
    RequestContext,
    User,
)

_DIGEST = "a" * 64


def _release(capability: PackCapability) -> PackRelease:
    return PackRelease(
        manifest=PackManifest(
            schema_version="1",
            id="org.example.operations-basics",
            name="Operations Basics",
            version="1.0.0",
            pack_type=PackType.FUNCTIONAL,
            core_version_range=">=0.1.0 <1.0.0",
            capabilities=[capability],
            content_checksums=[PackContentChecksum(path="README.md", sha256=_DIGEST)],
            publisher="Platform Curators",
        ),
        content_sha256=_DIGEST,
        registry_locator="org.example.operations-basics/1.0.0",
    )


class _Registry:
    def __init__(self, release: PackRelease) -> None:
        self.release = release

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(valid=True, releases=[self.release])


class _Store:
    def __init__(self, release: PackRelease) -> None:
        self.release = release
        self.rows: dict[str, PackInstallation] = {}
        self.provenance: list[tuple[object, ...]] = []
        self.block_uninstall = False

    def get(self, organization_id: UUID, pack_id: str) -> PackInstallation | None:
        return self.rows.get(pack_id)

    def installations(self, organization_id: UUID) -> list[PackInstallation]:
        return list(self.rows.values())

    def create(self, installation: PackInstallation) -> None:
        self.rows[installation.pack_id] = installation

    def update(self, installation: PackInstallation, expected_row_version: int) -> bool:
        current = self.rows.get(installation.pack_id)
        if current is None or current.row_version != expected_row_version:
            return False
        self.rows[installation.pack_id] = installation
        return True

    def add_provenance(self, *args: object) -> None:
        self.provenance.append(args)

    def registry_release(self, pack_id: str, version: str) -> PackRelease | None:
        return (
            self.release
            if self.release.manifest.id == pack_id and self.release.manifest.version == version
            else None
        )

    def has_materialized_artifacts(self, organization_id: UUID, pack_id: str) -> bool:
        return self.block_uninstall


class _Authorization:
    def __init__(self, permitted: bool = True) -> None:
        self.permitted = permitted

    def require(self, context: RequestContext, permission: str, scope: Scope) -> User:
        if not self.permitted:
            raise ServiceError(403, "access_denied")
        assert permission in {"domain_pack.install", "organization.read"}
        assert scope.type == ScopeType.ORGANIZATION
        return User(uuid4(), scope.organization_id, "issuer", "subject", "x@example.com", True)


class _Organizations:
    def active(self, organization_id: UUID) -> object:
        return object()

    def lock(self, organization_id: UUID) -> None:
        return None


class _Audit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def _service(
    capability: PackCapability = PackCapability.LOCALIZATION, permitted: bool = True
) -> tuple[DomainPackService, _Store, _Audit, UUID, RequestContext]:
    release = _release(capability)
    store = _Store(release)
    audit = _Audit()
    service = DomainPackService(
        _Registry(release), store, _Authorization(permitted), _Organizations(), audit, "0.1.0"
    )
    organization_id = uuid4()
    actor = RequestContext(Principal("issuer", "subject"), uuid4(), uuid4())
    return service, store, audit, organization_id, actor


def test_preview_bound_install_emits_audit_and_immutable_provenance() -> None:
    service, store, audit, organization_id, actor = _service()
    plan = service.plan(
        actor,
        organization_id,
        LifecyclePlanRequest(
            operation=LifecycleOperation.INSTALL,
            pack_id="org.example.operations-basics",
            version_range="=1.0.0",
        ),
    )
    assert plan.plan_sha256 is not None
    service.apply(
        actor,
        organization_id,
        LifecycleApplyRequest(
            operation=LifecycleOperation.INSTALL,
            pack_id="org.example.operations-basics",
            version_range="=1.0.0",
            expected_plan_sha256=plan.plan_sha256,
            reason="Approved pack rollout",
        ),
    )

    assert store.rows["org.example.operations-basics"].version == "1.0.0"
    assert len(store.provenance) == 1
    assert len(audit.events) == 1
    assert audit.events[0].type == "domain_pack.install"
    assert audit.events[0].payload.pack_id == "org.example.operations-basics"


def test_apply_rejects_stale_preview() -> None:
    service, _, _, organization_id, actor = _service()
    with pytest.raises(ServiceError, match="domain_pack_plan_stale"):
        service.apply(
            actor,
            organization_id,
            LifecycleApplyRequest(
                operation=LifecycleOperation.INSTALL,
                pack_id="org.example.operations-basics",
                version_range="=1.0.0",
                expected_plan_sha256="b" * 64,
                reason="Approved pack rollout",
            ),
        )


def test_install_is_denied_without_server_side_permission() -> None:
    service, _, _, organization_id, actor = _service(permitted=False)
    with pytest.raises(ServiceError, match="access_denied"):
        service.plan(
            actor,
            organization_id,
            LifecyclePlanRequest(
                operation=LifecycleOperation.INSTALL,
                pack_id="org.example.operations-basics",
                version_range="=1.0.0",
            ),
        )


def test_uninstall_requires_disable_first_and_preserves_artifacts() -> None:
    service, store, _, organization_id, actor = _service()
    now = datetime.now(UTC)
    store.rows["org.example.operations-basics"] = PackInstallation(
        id=uuid4(),
        organization_id=organization_id,
        pack_id="org.example.operations-basics",
        version="1.0.0",
        content_sha256=_DIGEST,
        state=InstallationState.ENABLED,
        row_version=1,
        created_at=now,
        updated_at=now,
        installed_by=uuid4(),
    )
    result = service.plan(
        actor,
        organization_id,
        LifecyclePlanRequest(
            operation=LifecycleOperation.UNINSTALL,
            pack_id="org.example.operations-basics",
        ),
    )

    assert not result.valid
    assert "installation.disable_first" in {issue.code for issue in result.issues}


def test_uninstall_refused_after_provenance_exists() -> None:
    service, store, _, organization_id, actor = _service()
    now = datetime.now(UTC)
    store.rows["org.example.operations-basics"] = PackInstallation(
        id=uuid4(),
        organization_id=organization_id,
        pack_id="org.example.operations-basics",
        version="1.0.0",
        content_sha256=_DIGEST,
        state=InstallationState.DISABLED,
        row_version=2,
        created_at=now,
        updated_at=now,
        installed_by=uuid4(),
    )
    store.provenance.append(("historical",))
    store.block_uninstall = True
    result = service.plan(
        actor,
        organization_id,
        LifecyclePlanRequest(
            operation=LifecycleOperation.UNINSTALL,
            pack_id="org.example.operations-basics",
        ),
    )

    assert not result.valid
    assert "installation.has_live_artifacts" in {issue.code for issue in result.issues}
