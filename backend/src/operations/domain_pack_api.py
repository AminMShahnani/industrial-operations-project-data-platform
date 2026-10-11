"""HTTP endpoints for organization-scoped Domain Pack catalog and lifecycle."""

from uuid import UUID

from fastapi import APIRouter

from operations.api import Context, ServiceDependency
from operations.modules.domain_packs.application.contracts import (
    InstallationPage,
    LifecycleApplyRequest,
    LifecyclePlan,
    LifecyclePlanRequest,
)
from operations.modules.domain_packs.application.imports import (
    ArtifactImportResult,
    ImportApplyRequest,
    ImportPreview,
    ImportPreviewRequest,
    PackArtifactCatalogPage,
)
from operations.modules.domain_packs.application.registry import RegistrySnapshot

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/domain-packs", tags=["domain-packs"]
)


@router.get("/catalog", response_model=RegistrySnapshot)
def catalog(organization_id: UUID, actor: Context, service: ServiceDependency) -> RegistrySnapshot:
    return service.domain_packs.catalog(actor, organization_id)


@router.get("/installations", response_model=InstallationPage)
def installed(
    organization_id: UUID, actor: Context, service: ServiceDependency
) -> InstallationPage:
    return service.domain_packs.installed(actor, organization_id)


@router.post("/plans", response_model=LifecyclePlan)
def plan(
    organization_id: UUID,
    body: LifecyclePlanRequest,
    actor: Context,
    service: ServiceDependency,
) -> LifecyclePlan:
    result = service.domain_packs.plan(actor, organization_id, body)
    # Plans expose reviewable identifiers and digests, not pack contents.
    return result.public()


@router.post("/apply", response_model=InstallationPage)
def apply(
    organization_id: UUID,
    body: LifecycleApplyRequest,
    actor: Context,
    service: ServiceDependency,
) -> InstallationPage:
    return service.domain_packs.apply(actor, organization_id, body)


@router.post("/imports/preview", response_model=ImportPreview)
def preview_import(
    organization_id: UUID,
    body: ImportPreviewRequest,
    actor: Context,
    service: ServiceDependency,
) -> ImportPreview:
    return service.domain_pack_imports.preview(actor, organization_id, body)


@router.post("/imports", response_model=ArtifactImportResult)
def import_artifact(
    organization_id: UUID,
    body: ImportApplyRequest,
    actor: Context,
    service: ServiceDependency,
) -> ArtifactImportResult:
    return service.domain_pack_imports.apply(actor, organization_id, body)


@router.get("/catalog/{pack_id}/{version}/artifacts", response_model=PackArtifactCatalogPage)
def catalog_artifacts(
    organization_id: UUID,
    pack_id: str,
    version: str,
    actor: Context,
    service: ServiceDependency,
) -> PackArtifactCatalogPage:
    return service.domain_pack_imports.catalog_artifacts(actor, organization_id, pack_id, version)
