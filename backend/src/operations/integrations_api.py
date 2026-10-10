"""Permission-scoped webhook endpoint administration API."""

from uuid import UUID

from fastapi import APIRouter

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.integrations.application.contracts import (
    EndpointCreate,
    EndpointRevise,
    EndpointRevoke,
    EndpointView,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/webhook-endpoints",
    tags=["integrations"],
)


class EndpointPage(Command):
    items: list[EndpointView]
    next_cursor: UUID | None = None


@router.post("", response_model=EndpointView, status_code=201)
def create_endpoint(
    organization_id: UUID,
    command: EndpointCreate,
    actor: Context,
    services: ServiceDependency,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
) -> EndpointView:
    return EndpointView.from_version(
        services.webhook_endpoints.create(actor, organization_id, workspace_id, project_id, command)
    )


@router.get("", response_model=EndpointPage)
def endpoint_page(
    organization_id: UUID,
    actor: Context,
    services: ServiceDependency,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> EndpointPage:
    rows = services.webhook_endpoints.page(actor, organization_id, workspace_id, project_id, cursor)
    return EndpointPage(
        items=[EndpointView.from_version(row) for row in rows[:100]],
        next_cursor=rows[99].endpoint_id if len(rows) > 100 else None,
    )


@router.get("/{endpoint_id}/versions/{number}", response_model=EndpointView)
def endpoint_version(
    organization_id: UUID,
    endpoint_id: UUID,
    number: int,
    actor: Context,
    services: ServiceDependency,
) -> EndpointView:
    row = services.webhook_endpoints.version(actor, organization_id, endpoint_id, number)
    return EndpointView.from_version(row)


@router.post("/{endpoint_id}/versions", response_model=EndpointView, status_code=201)
def revise_endpoint(
    organization_id: UUID,
    endpoint_id: UUID,
    command: EndpointRevise,
    actor: Context,
    services: ServiceDependency,
) -> EndpointView:
    row = services.webhook_endpoints.revise(actor, organization_id, endpoint_id, command)
    return EndpointView.from_version(row)


@router.post("/{endpoint_id}/revoke", response_model=EndpointView)
def revoke_endpoint(
    organization_id: UUID,
    endpoint_id: UUID,
    command: EndpointRevoke,
    actor: Context,
    services: ServiceDependency,
) -> EndpointView:
    row = services.webhook_endpoints.revoke(
        actor,
        organization_id,
        endpoint_id,
        command.expected_version,
        command.reason.strip(),
    )
    return EndpointView.from_version(row)
