from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.notifications.application.email_contracts import (
    EmailDeliveryPage,
    EmailHistory,
    EmailReview,
    EmailState,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/email-deliveries", tags=["email recovery"]
)


class EmailReplayCommand(Command):
    dry_run: bool = True
    review_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, min_length=1, max_length=500, pattern=r"\S")
    acknowledge_uncertain: bool = False


@router.get("", response_model=EmailDeliveryPage)
def deliveries(
    organization_id: UUID,
    actor: Context,
    services: ServiceDependency,
    state: EmailState | None = None,
    cursor: UUID | None = None,
) -> EmailDeliveryPage:
    return services.email.page(actor, organization_id, state, cursor)


@router.get("/{delivery_id}", response_model=EmailHistory)
def history(
    organization_id: UUID, delivery_id: UUID, actor: Context, services: ServiceDependency
) -> EmailHistory:
    return services.email.history(actor, organization_id, delivery_id)


@router.post("/{delivery_id}/replay", response_model=EmailReview)
def replay(
    organization_id: UUID,
    delivery_id: UUID,
    command: EmailReplayCommand,
    actor: Context,
    services: ServiceDependency,
) -> EmailReview:
    return services.email.reviewed_replay(
        actor,
        organization_id,
        delivery_id,
        dry_run=command.dry_run,
        review_sha256=command.review_sha256,
        reason=command.reason,
        acknowledge_uncertain=command.acknowledge_uncertain,
    )
