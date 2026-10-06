"""Dramatiq transport; durable processing belongs to application services."""

from dramatiq import Message
from dramatiq.broker import Broker

from operations.modules.automation.application.events import DeliveryMessage


class DramatiqPublisher:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self.broker.declare_queue("operations")

    def publish(self, message: DeliveryMessage) -> None:
        self.broker.enqueue(
            Message(
                queue_name="operations",
                actor_name="consume_delivery",
                args=(str(message.organization_id), str(message.delivery_id)),
                kwargs={},
                options={"max_retries": 0},
            )
        )
