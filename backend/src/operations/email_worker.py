"""Composition and execution helpers for durable scoped SMTP delivery."""

import atexit
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.notifications.application.email_contracts import EmailTransport
from operations.modules.notifications.application.email_service import EmailService
from operations.modules.notifications.infrastructure.email_persistence import EmailRepository
from operations.modules.notifications.infrastructure.smtp import SmtpTransport, load_profile
from operations.platform.config import Settings
from operations.platform.database import create_database_engine


def email_service(session: Session, settings: Settings | None = None) -> EmailService:
    return EmailService(EmailRepository(session), compose(session, settings=settings).notifications)


def process_email(
    org: UUID,
    identifier: UUID,
    settings: Settings,
    transport: EmailTransport | None = None,
    origin: str | None = None,
) -> None:
    engine = create_database_engine(settings)
    try:
        # Expired claims are recovered without needing provider credentials.
        with Session(engine) as session, session.begin():
            service = email_service(session, settings)
            service.identity.organizations.lock(org)
            current = service.store.get(org, identifier)
            if current is None or current.state not in {"pending", "retry", "sending"}:
                return
            if current.state == "sending":
                service.claim(org, identifier)
                return
        # Configuration failure does not consume an attempt or claim business work.
        if transport is None:
            profile = load_profile(
                settings.email_profiles_directory, org, settings.environment == "production"
            )
            transport, origin = SmtpTransport(profile), profile.app_origin
        if origin is None:
            raise ServiceError(503, "email_not_configured")
        with Session(engine) as session, session.begin():
            claimed = email_service(session, settings).claim(org, identifier)
        if claimed is None:
            return
        with Session(engine) as session, session.begin():
            service = email_service(session, settings)
            service.identity.organizations.lock(org)
            current = service.store.get(org, identifier)
            if (
                current is None
                or current.state != "sending"
                or current.attempts != claimed.attempts
            ):
                return
            try:
                content = service.render(claimed, origin)
            except ServiceError as error:
                if error.status in {403, 404}:
                    service.skip(claimed)
                    return
                raise
            result = transport.send(identifier, content)
            service.finish(claimed, result)
    except DBAPIError:
        raise ServiceError(503, "email_database_unavailable") from None
    finally:
        engine.dispose()


# Importing application helpers never starts a broker or reads provider secrets.
def register(settings: Settings | None = None, namespace: str = "dramatiq") -> RedisBroker:
    settings = settings or Settings()  # type: ignore[call-arg]
    broker = RedisBroker(
        url=settings.redis_url.get_secret_value(),
        namespace=namespace,
        socket_timeout=5,
        socket_connect_timeout=5,
    )  # type: ignore[no-untyped-call]

    @dramatiq.actor(broker=broker, queue_name="emails", max_retries=0, time_limit=60000)
    def consume_email(organization_id: str, delivery_id: str) -> None:
        process_email(UUID(organization_id), UUID(delivery_id), settings)

    def close() -> None:
        broker.close()
        broker.client.close()

    atexit.register(close)
    return broker
