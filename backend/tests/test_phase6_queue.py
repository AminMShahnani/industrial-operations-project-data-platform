from uuid import uuid7

import pytest
from dramatiq.brokers.redis import RedisBroker
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.infrastructure.queue import DramatiqPublisher
from operations.platform.config import Settings
from test_infrastructure import infrastructure_settings as infrastructure_settings

pytestmark = pytest.mark.integration


def test_real_redis_scoped_message_delivery(infrastructure_settings: Settings) -> None:
    # All queue cleanup is restricted to this unique fixture namespace.
    namespace = "phase6-test-" + str(uuid7())
    broker = RedisBroker(  # type: ignore[no-untyped-call]  # Vendor constructor lacks annotations.
        url=infrastructure_settings.redis_url.get_secret_value(),
        namespace=namespace,
        middleware=[],
        socket_timeout=3,
        socket_connect_timeout=3,
    )
    message = DeliveryMessage(organization_id=uuid7(), delivery_id=uuid7())
    consumer = None
    try:
        DramatiqPublisher(broker).publish(message)
        consumer = broker.consume("operations", prefetch=1, timeout=1000)
        received = next(consumer)
        assert received is not None
        assert received.actor_name == "consume_delivery"
        assert received.args == (str(message.organization_id), str(message.delivery_id))
        assert received.kwargs == {}
        consumer.ack(received)
    finally:
        if consumer:
            consumer.close()
        broker.flush("operations")
        broker.close()
        broker.client.close()
