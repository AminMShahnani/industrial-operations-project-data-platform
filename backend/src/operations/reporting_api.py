from uuid import UUID

from fastapi import APIRouter

from operations.api import Context, ServiceDependency
from operations.modules.reporting.application.contracts import OverdueTaskPage

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports",
    tags=["reporting"],
)


@router.get("/overdue-tasks", response_model=OverdueTaskPage)
def overdue_tasks(
    organization_id: UUID,
    workspace_id: UUID,
    context: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> OverdueTaskPage:
    return services.reporting.overdue_tasks(
        context, organization_id, workspace_id, project_id, cursor
    )
