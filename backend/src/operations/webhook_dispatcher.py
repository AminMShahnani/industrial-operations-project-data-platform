"""Dispatch due webhook delivery IDs to the separate Dramatiq worker."""

from uuid import UUID

from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.orm import Session

from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.webhook_worker import WebhookPublisher, publish_due, register


class DramatiqWebhookPublisher(WebhookPublisher):
    def __init__(self, broker: RedisBroker) -> None:
        self.broker = broker

    def publish(self, organization_id: UUID, delivery_id: UUID) -> None:
        self.broker.get_actor("consume_webhook").send(str(organization_id), str(delivery_id))


def dispatch_due(settings: Settings | None = None) -> int:
    settings = settings or Settings()  # type: ignore[call-arg]
    broker = register(settings)
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            return publish_due(session, DramatiqWebhookPublisher(broker))
    finally:
        broker.close()
        broker.client.close()
        engine.dispose()


if __name__ == "__main__":
    print(dispatch_due())
