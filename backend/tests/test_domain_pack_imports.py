from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from operations.contracts import ServiceError
from operations.modules.domain_packs.application.artifacts import validate_artifact
from operations.modules.domain_packs.application.contracts import (
    InstallationState,
    PackArtifactImport,
    PackInstallation,
)
from operations.modules.domain_packs.application.dependency_resolution import PackRelease
from operations.modules.domain_packs.application.imports import (
    ArtifactReader,
    DomainPackImportService,
    ImportApplyRequest,
    ImportPreviewRequest,
)
from operations.modules.domain_packs.application.manifest import PackManifest
from operations.modules.forms.application.service import FormService
from operations.modules.iam.application.contracts import Scope
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import Principal, RequestContext, User
from operations.modules.master_data.application.service import MasterDataService
from operations.modules.workflows.application.service import WorkflowService
from operations.modules.workspaces.application.service import WorkspaceService

ORG = UUID("22222222-2222-4222-8222-222222222222")
WORKSPACE = UUID("33333333-3333-4333-8333-333333333333")
USER = UUID("44444444-4444-4444-8444-444444444444")
DIGEST = "a" * 64
CONTEXT = RequestContext(Principal("https://issuer.example", "operator"), uuid4(), uuid4())


class _Authorization:
    def __init__(self) -> None:
        self.denied = False

    def user(self, context: RequestContext, organization_id: UUID) -> User:
        assert organization_id == ORG
        return User(USER, ORG, "https://issuer.example", "operator", "op@example.test", True)

    def require(self, context: RequestContext, permission: str, scope: Scope) -> User:
        if self.denied:
            raise ServiceError(403, "access_denied")
        return self.user(context, scope.organization_id)


class _InstallationStore:
    def __init__(self) -> None:
        self.installation = PackInstallation(
            id=uuid4(),
            organization_id=ORG,
            pack_id="org.example.oil-gas",
            version="1.0.0",
            content_sha256=DIGEST,
            state=InstallationState.INSTALLED,
            row_version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            installed_by=USER,
        )
        manifest = PackManifest.model_validate(
            {
                "schema_version": "1",
                "id": "org.example.oil-gas",
                "name": "Oil & Gas Starter",
                "version": "1.0.0",
                "pack_type": "industry",
                "core_version_range": ">=0.1.0 <1.0.0",
                "dependencies": [],
                "capabilities": ["forms"],
                "content_checksums": [{"path": "forms/readme.json", "sha256": DIGEST}],
                "publisher": "Platform Curators",
            }
        )
        self.release = PackRelease(
            manifest=manifest,
            content_sha256=DIGEST,
            registry_locator="org.example.oil-gas/1.0.0",
            migration_operations=[],
        )

    def get(self, organization_id: UUID, pack_id: str) -> PackInstallation | None:
        return (
            self.installation
            if organization_id == ORG and pack_id == self.installation.pack_id
            else None
        )

    def registry_release(self, pack_id: str, version: str) -> PackRelease | None:
        return (
            self.release
            if (pack_id, version) == (self.release.manifest.id, self.release.manifest.version)
            else None
        )


class _ImportStore:
    def __init__(self) -> None:
        self.by_key: dict[UUID, PackArtifactImport] = {}

    def get_by_key(self, organization_id: UUID, key: UUID) -> PackArtifactImport | None:
        return self.by_key.get(key)

    def get_source(self, *args: object) -> PackArtifactImport | None:
        return None

    def create(self, result: PackArtifactImport) -> None:
        self.by_key[result.idempotency_key] = result


class _Workspace:
    def active(self, organization_id: UUID, workspace_id: UUID) -> None:
        assert (organization_id, workspace_id) == (ORG, WORKSPACE)


class _Registry:
    def __init__(self, artifact: object) -> None:
        self.artifact = artifact

    def artifacts(self, pack_id: str, version: str) -> list[object]:
        return [self.artifact]


class _Forms:
    def __init__(self) -> None:
        self.created = 0
        self.form_id = uuid4()

    def create(self, *args: object) -> SimpleNamespace:
        self.created += 1
        return SimpleNamespace(id=self.form_id)


def _artifact() -> object:
    return validate_artifact(
        {
            "schema_version": 1,
            "artifact_id": "daily-report",
            "artifact_version": 1,
            "kind": "form",
            "name": "Daily report",
            "definition": {
                "sections": [
                    {
                        "key": "general",
                        "label": "General",
                        "components": [{"key": "report_date", "kind": "date", "label": "Date"}],
                    }
                ]
            },
        }
    )


def _service() -> tuple[DomainPackImportService, _Forms, _ImportStore, _Authorization]:
    forms = _Forms()
    imports = _ImportStore()
    authorization = _Authorization()
    service = DomainPackImportService(
        cast(ArtifactReader, _Registry(_artifact())),
        _InstallationStore(),  # type: ignore[arg-type]
        imports,
        cast(Authorization, authorization),
        cast(WorkspaceService, _Workspace()),
        SimpleNamespace(),
        cast(FormService, forms),
        cast(MasterDataService, object()),
        cast(WorkflowService, object()),
    )
    return service, forms, imports, authorization


def _request(key: UUID | None = None) -> ImportPreviewRequest:
    return ImportPreviewRequest(
        pack_id="org.example.oil-gas",
        pack_version="1.0.0",
        artifact_id="daily-report",
        artifact_version=1,
        workspace_id=WORKSPACE,
        idempotency_key=key or uuid4(),
    )


def test_preview_apply_and_retry_are_idempotent() -> None:
    service, forms, imports, authorization = _service()
    request = _request()
    preview = service.preview(CONTEXT, ORG, request)
    assert preview.preview_sha256 is not None

    result = service.apply(
        CONTEXT,
        ORG,
        ImportApplyRequest(**request.model_dump(), expected_preview_sha256=preview.preview_sha256),
    )
    replay = service.apply(
        CONTEXT,
        ORG,
        ImportApplyRequest(**request.model_dump(), expected_preview_sha256=preview.preview_sha256),
    )

    assert result.target_id == forms.form_id
    assert replay.id == result.id
    assert forms.created == 1
    assert len(imports.by_key) == 1
    authorization.denied = True
    retry = ImportApplyRequest(
        **request.model_dump(), expected_preview_sha256=preview.preview_sha256
    )
    with pytest.raises(ServiceError, match="access_denied"):
        service.apply(CONTEXT, ORG, retry)


def test_preview_digest_tampering_and_permission_denial_fail_closed() -> None:
    service, forms, _, authorization = _service()
    request = _request()
    service.preview(CONTEXT, ORG, request)
    with pytest.raises(ServiceError, match="domain_pack_import_preview_stale"):
        service.apply(
            CONTEXT,
            ORG,
            ImportApplyRequest(**request.model_dump(), expected_preview_sha256="b" * 64),
        )
    authorization.denied = True
    with pytest.raises(ServiceError, match="access_denied"):
        service.preview(CONTEXT, ORG, _request())
    assert forms.created == 0


def test_catalog_only_exposes_current_installed_release() -> None:
    service, _, _, _ = _service()

    page = service.catalog_artifacts(CONTEXT, ORG, "org.example.oil-gas", "1.0.0")

    assert len(page.items) == 1
    assert page.items[0].artifact_id == "daily-report"
