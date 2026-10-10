"""Dispatch due webhook delivery IDs to the separate Dramatiq worker."""

import argparse
import logging
import time
from uuid import UUID

from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.orm import Session

from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.platform.logging import configure_logging
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval-seconds", type=int, default=0, help="Repeat polling at this interval"
    )
    args = parser.parse_args()
    if args.interval_seconds < 0 or args.interval_seconds > 3600:
        parser.error("--interval-seconds must be between 0 and 3600")
    if args.interval_seconds == 0:
        print(dispatch_due())
        return
    configure_logging()
    while True:
        try:
            dispatched = dispatch_due()
            logging.getLogger("operations.webhooks").info(
                "webhook.dispatcher.completed", extra={"dispatched": dispatched}
            )
        except Exception:
            logging.getLogger("operations.webhooks").exception("webhook.dispatcher.failed")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
