"""Preview-bound, idempotent imports from organization pack catalogs."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid7

from pydantic import Field, StrictStr

from operations.contracts import Command, ServiceError
from operations.modules.audit.application.contracts import AuditDetails
from operations.modules.domain_packs.application.artifacts import (
    PackArtifactEnvelope,
    PackArtifactKind,
    PackAutomationTemplateArtifact,
    PackAutomationTemplateDefinition,
    PackFormArtifact,
    PackKpiArtifact,
    PackMappingProfileArtifact,
    PackMappingProfileDefinition,
    PackMasterDataTypeArtifact,
    PackWorkflowArtifact,
    ValidatedPackArtifact,
)
from operations.modules.domain_packs.application.contracts import (
    InstallationState,
    PackArtifactImport,
    PackArtifactImportStore,
    PackInstallationStore,
)
from operations.modules.forms.application.service import FormService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.iam.application.service import Authorization
from operations.modules.identity.application.contracts import RequestContext, User
from operations.modules.master_data.application.contracts import (
    DataScope,
)
from operations.modules.master_data.application.service import MasterDataService
from operations.modules.reporting.application.contracts import SavedKpiDefinition
from operations.modules.reporting.application.datasets import ReportingService
from operations.modules.workflows.application.service import WorkflowService
from operations.modules.workspaces.application.service import WorkspaceService


class ArtifactReader(Protocol):
    def artifacts(self, pack_id: str, version: str) -> list[ValidatedPackArtifact]: ...


class ImportPreviewRequest(Command):
    pack_id: str = Field(min_length=3, max_length=180)
    pack_version: str = Field(min_length=5, max_length=128)
    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    artifact_version: int = Field(ge=1)
    workspace_id: UUID
    project_id: UUID | None = None
    idempotency_key: UUID


class ImportPreview(Command):
    valid: bool
    preview_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    pack_id: str
    pack_version: str
    package_sha256: str | None = None
    artifact_id: str
    artifact_version: int
    artifact_kind: PackArtifactKind | None = None
    name: str | None = None
    workspace_id: UUID
    project_id: UUID | None = None
    idempotency_key: UUID
    issues: list[StrictStr] = Field(default_factory=list)


class ImportApplyRequest(ImportPreviewRequest):
    expected_preview_sha256: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactImportResult(Command):
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
    inert_definition: PackAutomationTemplateDefinition | PackMappingProfileDefinition | None = None


class PackArtifactCatalogPage(Command):
    items: list[PackArtifactEnvelope] = Field(max_length=1000)


class ImportProjectAccess(Protocol):
    def require_access(
        self,
        context: RequestContext,
        organization_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        permission: str,
    ) -> object: ...


class DomainPackImportService:
    def __init__(
        self,
        registry: ArtifactReader,
        installations: PackInstallationStore,
        imports: PackArtifactImportStore,
        authorization: Authorization,
        workspaces: WorkspaceService,
        projects: ImportProjectAccess,
        forms: FormService,
        master_data: MasterDataService,
        workflows: WorkflowService,
        reporting: ReportingService | None = None,
    ) -> None:
        self.registry = registry
        self.installations = installations
        self.imports = imports
        self.authorization = authorization
        self.workspaces = workspaces
        self.projects = projects
        self.forms = forms
        self.master_data = master_data
        self.workflows = workflows
        self.reporting = reporting

    def catalog_artifacts(
        self, context: RequestContext, organization_id: UUID, pack_id: str, version: str
    ) -> PackArtifactCatalogPage:
        self.authorization.require(
            context,
            "organization.read",
            Scope(organization_id, ScopeType.ORGANIZATION, organization_id),
        )
        installation = self.installations.get(organization_id, pack_id)
        if (
            installation is None
            or installation.version != version
            or installation.state not in {InstallationState.INSTALLED, InstallationState.ENABLED}
        ):
            raise ServiceError(404, "domain_pack_catalog_release_not_available")
        release = self.installations.registry_release(pack_id, version)
        if release is None or release.content_sha256 != installation.content_sha256:
            raise ServiceError(409, "domain_pack_catalog_release_stale")
        artifacts = self.registry.artifacts(pack_id, version)
        return PackArtifactCatalogPage(items=[artifact.envelope for artifact in artifacts])

    def preview(
        self, context: RequestContext, organization_id: UUID, request: ImportPreviewRequest
    ) -> ImportPreview:
        actor, artifact, digest = self._prepare(context, organization_id, request)
        existing = self.imports.get_by_key(organization_id, request.idempotency_key)
        if existing is not None:
            if self._same_request(existing, request, digest):
                return self._preview_result(request, digest, artifact)
            raise ServiceError(409, "domain_pack_import_idempotency_conflict")
        if self._source_import(organization_id, request) is not None:
            raise ServiceError(409, "domain_pack_artifact_already_imported")
        self._authorize_target(context, organization_id, request, artifact.envelope.kind)
        self._require_imported_references(organization_id, request, artifact)
        self._validate_kpi(context, organization_id, request, artifact)
        return self._preview_result(request, digest, artifact)

    def apply(
        self,
        context: RequestContext,
        organization_id: UUID,
        request: ImportApplyRequest,
    ) -> ArtifactImportResult:
        actor, artifact, digest = self._prepare(context, organization_id, request)
        previous = self.imports.get_by_key(organization_id, request.idempotency_key)
        if previous is not None:
            if previous.imported_by == actor.id and self._same_request(previous, request, digest):
                self._authorize_target(context, organization_id, request, artifact.envelope.kind)
                return ArtifactImportResult(
                    **previous.model_dump(),
                    inert_definition=self._inert_definition(organization_id, request, artifact),
                )
            raise ServiceError(409, "domain_pack_import_idempotency_conflict")
        preview = self._preview_result(request, digest, artifact)
        if not preview.valid or preview.preview_sha256 != request.expected_preview_sha256:
            raise ServiceError(409, "domain_pack_import_preview_stale")
        self._authorize_target(context, organization_id, request, artifact.envelope.kind)
        if self._source_import(organization_id, request) is not None:
            raise ServiceError(409, "domain_pack_artifact_already_imported")
        self._require_imported_references(organization_id, request, artifact)
        self._validate_kpi(context, organization_id, request, artifact)
        target_id = self._materialize(context, organization_id, request, artifact, digest)
        result = PackArtifactImport(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            idempotency_key=request.idempotency_key,
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            package_sha256=digest,
            artifact_id=request.artifact_id,
            artifact_version=request.artifact_version,
            artifact_kind=artifact.envelope.kind.value,
            target_id=target_id,
            imported_by=actor.id,
            created_at=datetime.now(UTC),
        )
        self.imports.create(result)
        return ArtifactImportResult(
            **result.model_dump(),
            inert_definition=self._inert_definition(organization_id, request, artifact),
        )

    def _prepare(
        self, context: RequestContext, organization_id: UUID, request: ImportPreviewRequest
    ) -> tuple[User, ValidatedPackArtifact, str]:
        self.workspaces.active(organization_id, request.workspace_id)
        self.authorization.user(context, organization_id)
        installation = self.installations.get(organization_id, request.pack_id)
        if (
            installation is None
            or installation.version != request.pack_version
            or installation.state not in {InstallationState.INSTALLED, InstallationState.ENABLED}
        ):
            raise ServiceError(404, "domain_pack_catalog_release_not_available")
        artifacts = self.registry.artifacts(request.pack_id, request.pack_version)
        selected = next(
            (
                item
                for item in artifacts
                if item.envelope.artifact_id == request.artifact_id
                and item.envelope.artifact_version == request.artifact_version
            ),
            None,
        )
        if selected is None:
            raise ServiceError(404, "domain_pack_artifact_not_found")
        # The registry adapter returns only validated immutable releases. Installation
        # provenance still binds access to the installed release checksum.
        release = self.installations.registry_release(request.pack_id, request.pack_version)
        if release is None or release.content_sha256 != installation.content_sha256:
            raise ServiceError(409, "domain_pack_catalog_release_stale")
        return self.authorization.user(context, organization_id), selected, release.content_sha256

    def _authorize_target(
        self,
        context: RequestContext,
        organization_id: UUID,
        request: ImportPreviewRequest,
        kind: PackArtifactKind,
    ) -> None:
        permission = {
            PackArtifactKind.FORM: "form.manage",
            PackArtifactKind.MASTER_DATA_TYPE: "master_data.manage",
            PackArtifactKind.WORKFLOW: "workflow.manage",
            PackArtifactKind.KPI: "submission.read",
            PackArtifactKind.AUTOMATION_TEMPLATE: "automation.manage",
            PackArtifactKind.MAPPING_PROFILE: "workspace.read",
        }.get(kind)
        if permission is None:
            raise ServiceError(422, "domain_pack_artifact_import_unsupported")
        if request.project_id is None:
            self.authorization.require(
                context,
                permission,
                Scope(organization_id, ScopeType.WORKSPACE, request.workspace_id),
            )
        else:
            if kind == PackArtifactKind.MAPPING_PROFILE:
                permission = "project.read"
            self.projects.require_access(
                context,
                organization_id,
                request.workspace_id,
                request.project_id,
                permission,
            )

    def _preview_result(
        self,
        request: ImportPreviewRequest,
        package_sha256: str,
        artifact: ValidatedPackArtifact,
    ) -> ImportPreview:
        plan = {
            "pack_id": request.pack_id,
            "pack_version": request.pack_version,
            "package_sha256": package_sha256,
            "artifact_id": request.artifact_id,
            "artifact_version": request.artifact_version,
            "artifact_kind": artifact.envelope.kind.value,
            "workspace_id": str(request.workspace_id),
            "project_id": str(request.project_id) if request.project_id else None,
            "idempotency_key": str(request.idempotency_key),
        }
        digest = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ImportPreview(
            valid=True,
            preview_sha256=digest,
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            package_sha256=package_sha256,
            artifact_id=request.artifact_id,
            artifact_version=request.artifact_version,
            artifact_kind=artifact.envelope.kind,
            name=artifact.envelope.name,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            idempotency_key=request.idempotency_key,
            issues=[],
        )

    def _source_import(
        self, organization_id: UUID, request: ImportPreviewRequest
    ) -> PackArtifactImport | None:
        return self.imports.get_source(
            organization_id,
            request.workspace_id,
            request.project_id,
            request.pack_id,
            request.pack_version,
            request.artifact_id,
            request.artifact_version,
        )

    def _require_imported_references(
        self,
        organization_id: UUID,
        request: ImportPreviewRequest,
        artifact: ValidatedPackArtifact,
    ) -> None:
        for reference in artifact.references:
            imported = self.imports.get_source(
                organization_id,
                request.workspace_id,
                request.project_id,
                reference.pack_id,
                reference.pack_version,
                reference.artifact_id,
                reference.version,
            )
            if imported is None or imported.artifact_kind != reference.kind.value:
                raise ServiceError(409, "domain_pack_artifact_dependency_import_required")

    def _mapped_definition(
        self,
        organization_id: UUID,
        request: ImportPreviewRequest,
        artifact: ValidatedPackArtifact,
    ) -> dict[str, object]:
        mappings: dict[str, str] = {}
        for reference in artifact.references:
            imported = self.imports.get_source(
                organization_id,
                request.workspace_id,
                request.project_id,
                reference.pack_id,
                reference.pack_version,
                reference.artifact_id,
                reference.version,
            )
            if imported is None:
                raise ServiceError(409, "domain_pack_artifact_dependency_import_required")
            mappings[str(reference.token())] = str(imported.target_id)

        def replace(value: object) -> object:
            if isinstance(value, str):
                return mappings.get(value, value)
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            return value

        definition = artifact.definition.model_dump(mode="json")
        mapped = replace(definition)
        if not isinstance(mapped, dict):
            raise ServiceError(422, "domain_pack_artifact_definition_invalid")
        return mapped

    def _validate_kpi(
        self,
        context: RequestContext,
        organization_id: UUID,
        request: ImportPreviewRequest,
        artifact: ValidatedPackArtifact,
    ) -> None:
        if not isinstance(artifact, PackKpiArtifact):
            return
        if self.reporting is None:
            raise ServiceError(503, "kpi_reporting_unavailable")
        self.reporting.validate_pack_kpi(
            context,
            organization_id,
            request.workspace_id,
            request.project_id,
            SavedKpiDefinition.model_validate(
                self._mapped_definition(organization_id, request, artifact)
            ),
        )

    def _inert_definition(
        self,
        organization_id: UUID,
        request: ImportPreviewRequest,
        artifact: ValidatedPackArtifact,
    ) -> PackAutomationTemplateDefinition | PackMappingProfileDefinition | None:
        if isinstance(artifact, PackAutomationTemplateArtifact):
            return PackAutomationTemplateDefinition.model_validate(
                self._mapped_definition(organization_id, request, artifact)
            )
        if isinstance(artifact, PackMappingProfileArtifact):
            return artifact.definition
        return None

    def _materialize(
        self,
        context: RequestContext,
        organization_id: UUID,
        request: ImportPreviewRequest,
        artifact: ValidatedPackArtifact,
        package_sha256: str,
    ) -> UUID:
        provenance = AuditDetails(
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            pack_artifact_id=request.artifact_id,
            pack_artifact_version=request.artifact_version,
            package_sha256=package_sha256,
        )
        if isinstance(artifact, PackFormArtifact):
            from operations.modules.forms.application.contracts import FormDefinition

            form = self.forms.create(
                context,
                organization_id,
                request.workspace_id,
                request.project_id,
                artifact.envelope.name,
                FormDefinition.model_validate(
                    self._mapped_definition(organization_id, request, artifact)
                ),
                provenance,
            )
            return form.id
        if isinstance(artifact, PackMasterDataTypeArtifact):
            from operations.modules.master_data.application.contracts import DataSchema

            return self.master_data.create_type(
                context,
                organization_id,
                DataScope.PROJECT if request.project_id else DataScope.WORKSPACE,
                request.workspace_id,
                request.project_id,
                artifact.definition.code,
                artifact.definition.name,
                artifact.definition.registry,
                DataSchema.model_validate(
                    self._mapped_definition(organization_id, request, artifact)["definition"]
                ),
                provenance,
            ).id
        if isinstance(artifact, PackWorkflowArtifact):
            reference = artifact.references[0]
            imported_form = self.imports.get_source(
                organization_id,
                request.workspace_id,
                request.project_id,
                reference.pack_id,
                reference.pack_version,
                reference.artifact_id,
                reference.version,
            )
            if imported_form is None or imported_form.artifact_kind != PackArtifactKind.FORM.value:
                raise ServiceError(409, "domain_pack_workflow_form_must_be_imported_first")
            definition = artifact.definition.model_copy(update={"form_id": imported_form.target_id})
            return self.workflows.create_template_draft(
                context,
                organization_id,
                request.workspace_id,
                request.project_id,
                artifact.envelope.name,
                definition,
                provenance,
            ).id
        if isinstance(artifact, (PackAutomationTemplateArtifact, PackMappingProfileArtifact)):
            # These artifacts are imported as inert, typed Domain Pack templates.
            # The import ledger is their owner; activation or record transformation
            # requires a separate explicit user workflow.
            self._inert_definition(organization_id, request, artifact)
            return uuid7()
        if isinstance(artifact, PackKpiArtifact):
            if self.reporting is None:
                raise ServiceError(503, "kpi_reporting_unavailable")
            return self.reporting.import_pack_kpi(
                context,
                organization_id,
                request.workspace_id,
                request.project_id,
                artifact.envelope.name,
                SavedKpiDefinition.model_validate(
                    self._mapped_definition(organization_id, request, artifact)
                ),
                provenance,
            ).id
        raise ServiceError(422, "domain_pack_artifact_import_unsupported")

    @staticmethod
    def _same_request(
        previous: PackArtifactImport, request: ImportPreviewRequest, package_sha256: str
    ) -> bool:
        return (
            previous.workspace_id == request.workspace_id
            and previous.project_id == request.project_id
            and previous.pack_id == request.pack_id
            and previous.pack_version == request.pack_version
            and previous.package_sha256 == package_sha256
            and previous.artifact_id == request.artifact_id
            and previous.artifact_version == request.artifact_version
        )
