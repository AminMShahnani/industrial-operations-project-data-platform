"""Composition root for scoped durable job execution; broker payloads carry IDs only."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from dramatiq import Actor
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.automation.application.consumer import AutomationConsumer
from operations.modules.automation.application.events import Delivery, DeliveryMessage
from operations.platform.config import Settings
from operations.platform.database import create_database_engine


@contextmanager
def action_savepoint(session: Session) -> Generator[None]:
    try:
        with session.begin_nested():
            yield
    except IntegrityError:
        raise ServiceError(409, "automation_persistence_integrity") from None
    except DBAPIError:
        # No database detail or action content is copied into jobs, logs or evidence.
        raise ServiceError(503, "automation_dependency_transient") from None


def process_automation(
    session: Session, message: DeliveryMessage, settings: Settings | None = None
) -> Delivery:
    return AutomationConsumer(
        compose(session, settings=settings).automation, lambda: action_savepoint(session)
    ).consume(message)


@dataclass(frozen=True)
class WorkerRuntime:
    broker: RedisBroker
    actor: Actor[[str, str], None]
    engine: Engine

    def close(self) -> None:
        self.broker.close()
        self.broker.client.close()
        self.engine.dispose()


def register_actor(settings: Settings, namespace: str = "dramatiq") -> WorkerRuntime:
    broker = RedisBroker(  # type: ignore[no-untyped-call]  # Vendor constructor lacks annotations.
        url=settings.redis_url.get_secret_value(),
        namespace=namespace,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    engine = create_database_engine(settings)
    sessions = sessionmaker(engine, expire_on_commit=False)

    def consume_delivery(organization_id: str, delivery_id: str) -> None:
        try:
            message = DeliveryMessage(
                organization_id=UUID(organization_id), delivery_id=UUID(delivery_id)
            )
        except ValueError:
            raise ServiceError(422, "invalid_delivery_message") from None
        try:
            with sessions.begin() as session:
                process_automation(session, message, settings)
        except DBAPIError:
            raise ServiceError(503, "worker_database_unavailable") from None

    actor = Actor(
        consume_delivery,
        broker=broker,
        actor_name="consume_delivery",
        queue_name="operations",
        priority=0,
        options={"max_retries": 0},
    )
    return WorkerRuntime(broker, actor, engine)
