from datetime import UTC, datetime
from uuid import uuid7

import pytest
from dramatiq.brokers.stub import StubBroker
from operations.modules.automation.application.events import (
    DeliveryMessage,
    EventContext,
    OperationalEvent,
)
from operations.modules.automation.domain.reliability import (
    delivery_id,
    next_causation,
    retry_delay,
)
from operations.modules.automation.infrastructure.queue import DramatiqPublisher
from pydantic import ValidationError


def test_retry_backoff_is_bounded_and_exhausts() -> None:
    assert [retry_delay(attempt) for attempt in range(1, 9)] == [5, 10, 20, 40, 80, 160, 320, None]
    assert retry_delay(19, 20) == 3600
    for attempt, limit in ((0, 8), (9, 8), (1, 21), (1, 0)):
        with pytest.raises(ValueError):
            retry_delay(attempt, limit)


def test_event_consumer_identity_and_causation_prevent_duplicates_loops() -> None:
    event, version = uuid7(), uuid7()
    assert delivery_id(event, "automation") == delivery_id(event, "automation")
    assert delivery_id(event, "automation") != delivery_id(event, "notifications")
    with pytest.raises(ValueError):
        delivery_id(event, "arbitrary_code")
    path = next_causation((), version)
    with pytest.raises(ValueError):
        next_causation(path, version)
    with pytest.raises(ValueError):
        next_causation(tuple(uuid7() for _ in range(16)), uuid7())


def test_event_schema_rejects_untyped_payload_naive_time_and_executable_fields() -> None:
    event = OperationalEvent(
        id=uuid7(),
        type="task.created",
        occurred_at=datetime.now(UTC),
        organization_id=uuid7(),
        workspace_id=uuid7(),
        correlation_id=uuid7(),
        aggregate_type="task",
        aggregate_id=uuid7(),
    )
    for changes in (
        {"payload": {"secret": "must not enter event context"}},
        {"python": "print('not executable')"},
        {"occurred_at": datetime.now()},
        {"causation_path": [event.id, event.id]},
        {"payload_version": 2},
    ):
        with pytest.raises(ValidationError):
            OperationalEvent.model_validate({**event.model_dump(), **changes})
    with pytest.raises(ValidationError):
        EventContext(form_id=uuid7())


def test_broker_contains_only_scoped_ids_and_no_automatic_business_retry() -> None:
    broker = StubBroker(middleware=[])
    message = DeliveryMessage(organization_id=uuid7(), delivery_id=uuid7())
    DramatiqPublisher(broker).publish(message)
    consumer = broker.consume("operations")
    queued = next(consumer)
    assert queued is not None
    assert queued.args == (str(message.organization_id), str(message.delivery_id))
    assert queued.kwargs == {} and queued.options == {"max_retries": 0}
    consumer.ack(queued)
    consumer.close()
    broker.close()
