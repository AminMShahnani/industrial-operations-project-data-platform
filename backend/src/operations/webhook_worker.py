"""ID-only Dramatiq webhook delivery worker and durable intent poller."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRepository
from operations.modules.automation.infrastructure.persistence import AutomationRepository
from operations.modules.integrations.application.delivery import WebhookDeliveryService
from operations.modules.integrations.application.delivery_contracts import WebhookDeliveryState
from operations.modules.integrations.application.webhooks import (
    PinnedHTTPSWebhookTransport,
    TenantSecretResolver,
    UnconfiguredTenantSecretResolver,
    WebhookTransport,
)
from operations.modules.integrations.infrastructure.persistence import (
    WebhookDeliveryRepository,
    WebhookEndpointRepository,
)
from operations.platform.config import Settings
from operations.platform.database import create_database_engine


class WebhookPublisher(Protocol):
    def publish(self, organization_id: UUID, delivery_id: UUID) -> None: ...


def _service(
    session: Session,
    settings: Settings,
    secrets: TenantSecretResolver,
    transport: WebhookTransport,
) -> WebhookDeliveryService:
    return WebhookDeliveryService(
        WebhookDeliveryRepository(session),
        WebhookEndpointRepository(session),
        AutomationRepository(session),
        AuditRepository(session),
        secrets,
        transport,
        tuple(settings.webhook_private_egress_cidrs),
    )


def process_webhook(
    organization_id: UUID,
    delivery_id: UUID,
    settings: Settings,
    secrets: TenantSecretResolver | None = None,
    transport: WebhookTransport | None = None,
) -> WebhookDeliveryState | None:
    resolver = secrets or UnconfiguredTenantSecretResolver()
    if isinstance(resolver, UnconfiguredTenantSecretResolver):
        # Do not consume attempts while the deployment has not provided its secret manager.
        raise ServiceError(503, "webhook_signing_secret_unavailable")
    sender = transport or PinnedHTTPSWebhookTransport()
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            claimed = _service(session, settings, resolver, sender).claim(
                organization_id, delivery_id
            )
        if claimed is None:
            return None
        # Read/pin the source, endpoint version and current revocation head, then close
        # the transaction before DNS, secret-manager calls, signing or network I/O.
        with Session(engine) as session, session.begin():
            delivery = _service(session, settings, resolver, sender)
            snapshot = delivery.prepare(organization_id, delivery_id)
        outcome, error_code = delivery.transmit(snapshot, claimed.attempts)
        with Session(engine) as session, session.begin():
            result = _service(session, settings, resolver, sender).finish(
                organization_id, delivery_id, claimed, outcome, error_code
            )
        return result
    except DBAPIError:
        # A committed lease is recovered as uncertain after expiry if the send may have
        # happened; an uncommitted claim consumes nothing.
        raise ServiceError(503, "webhook_delivery_database_unavailable") from None
    finally:
        engine.dispose()


def publish_due(session: Session, publish: WebhookPublisher, now: datetime | None = None) -> int:
    """Republish due IDs safely; claim leases make duplicate queue messages harmless."""
    repository = WebhookDeliveryRepository(session)
    rows = repository.due(now or datetime.now(UTC))
    for row in rows:
        publish.publish(row.organization_id, row.id)
    return len(rows)


def register(
    settings: Settings | None = None,
    namespace: str = "dramatiq",
    secrets: TenantSecretResolver | None = None,
    transport: WebhookTransport | None = None,
) -> RedisBroker:
    settings = settings or Settings()  # type: ignore[call-arg]
    broker = RedisBroker(
        url=settings.redis_url.get_secret_value(),
        namespace=namespace,
        socket_timeout=5,
        socket_connect_timeout=5,
    )  # type: ignore[no-untyped-call]

    @dramatiq.actor(broker=broker, queue_name="webhooks", max_retries=0, time_limit=60000)
    def consume_webhook(organization: str, delivery: str) -> None:
        try:
            org_id, delivery_uuid = UUID(organization), UUID(delivery)
        except ValueError:
            raise ServiceError(422, "invalid_webhook_delivery_message") from None
        process_webhook(org_id, delivery_uuid, settings, secrets, transport)

    return broker
