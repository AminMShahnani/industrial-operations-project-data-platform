"""Scoped history and reviewed recovery for signed webhook deliveries."""

from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.integrations.application.delivery_contracts import (
    WebhookDeliveryHistory,
    WebhookDeliveryPage,
    WebhookDeliveryReview,
    WebhookDeliveryStatus,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/webhook-deliveries",
    tags=["webhook recovery"],
)


class WebhookReplayCommand(Command):
    dry_run: bool = True
    review_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, min_length=1, max_length=500, pattern=r"\S")
    acknowledge_uncertain: bool = False


@router.get("", response_model=WebhookDeliveryPage)
def deliveries(
    organization_id: UUID,
    actor: Context,
    services: ServiceDependency,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    state: WebhookDeliveryStatus | None = None,
    cursor: UUID | None = None,
) -> WebhookDeliveryPage:
    return services.webhook_deliveries.page(
        actor, organization_id, workspace_id, project_id, state, cursor
    )


@router.get("/{delivery_id}", response_model=WebhookDeliveryHistory)
def history(
    organization_id: UUID,
    delivery_id: UUID,
    actor: Context,
    services: ServiceDependency,
) -> WebhookDeliveryHistory:
    return services.webhook_deliveries.history(actor, organization_id, delivery_id)


@router.post("/{delivery_id}/replay", response_model=WebhookDeliveryReview)
def replay(
    organization_id: UUID,
    delivery_id: UUID,
    command: WebhookReplayCommand,
    actor: Context,
    services: ServiceDependency,
) -> WebhookDeliveryReview:
    return services.webhook_deliveries.replay(
        actor,
        organization_id,
        delivery_id,
        apply=not command.dry_run,
        review_sha256=command.review_sha256,
        reason=command.reason,
        acknowledge_uncertain=command.acknowledge_uncertain,
    )
