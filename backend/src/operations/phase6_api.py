from uuid import UUID

from fastapi import APIRouter

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.notifications.application.contracts import InboxItem, ReadReceipt

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}",
    tags=["notifications"],
)


class NotificationPage(Command):
    items: list[InboxItem]
    next_cursor: UUID | None


@router.get("/notifications", response_model=NotificationPage)
def inbox(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> NotificationPage:
    items, next_cursor = services.notifications.inbox(actor, organization_id, workspace_id, cursor)
    return NotificationPage(items=items, next_cursor=next_cursor)


@router.get("/notifications/{notification_id}", response_model=InboxItem)
def detail(
    organization_id: UUID,
    workspace_id: UUID,
    notification_id: UUID,
    actor: Context,
    services: ServiceDependency,
) -> InboxItem:
    return services.notifications.detail(actor, organization_id, workspace_id, notification_id)


@router.post("/notifications/{notification_id}/read", response_model=ReadReceipt)
def mark_read(
    organization_id: UUID,
    workspace_id: UUID,
    notification_id: UUID,
    actor: Context,
    services: ServiceDependency,
) -> ReadReceipt:
    # Bind the workspace route before invoking the serialized, freshly authorized write.
    services.notifications.detail(actor, organization_id, workspace_id, notification_id)
    return services.notifications.mark_read(actor, organization_id, notification_id)
