"""Composition root for scoped durable job execution; broker payloads carry IDs only."""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID, uuid7

from dramatiq import Actor
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.consumer import AutomationConsumer
from operations.modules.automation.application.events import Delivery, DeliveryMessage
from operations.modules.files.infrastructure.adapters import S3Storage
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.consumer import NotificationConsumer
from operations.modules.reporting.infrastructure.export_jobs import ReportExportJobRepository
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


def process_notifications(
    session: Session, message: DeliveryMessage, settings: Settings | None = None
) -> Delivery:
    services = compose(session, settings=settings)
    return NotificationConsumer(
        services.notifications, services.automation, lambda: action_savepoint(session)
    ).consume(message)


def record_export_state(
    session: Session,
    organization_id: UUID,
    job_id: UUID,
    report_id: UUID,
    workspace_id: UUID,
    reason: str,
    settings: Settings,
    state: str = "expired",
) -> None:
    compose(session, settings=settings).reporting.audit.append(
        AuditEvent(
            id=uuid7(),
            type=f"report.export.{state}",
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor_id=None,
            correlation_id=uuid7(),
            request_id=uuid7(),
            aggregate_type="report_export",
            aggregate_id=job_id,
            payload=AuditDetails(
                target_id=report_id,
                workspace_id=workspace_id,
                reason=reason,
            ),
        )
    )


@dataclass(frozen=True)
class WorkerRuntime:
    broker: RedisBroker
    actor: Actor[[str, str], None]
    engine: Engine
    stop_dispatcher: Event
    dispatcher: Thread

    def close(self) -> None:
        self.stop_dispatcher.set()
        self.dispatcher.join(timeout=2)
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
                service = compose(session, settings=settings).automation
                delivery = service.store.delivery(message.organization_id, message.delivery_id)
                if delivery is not None and delivery.consumer == "notifications":
                    process_notifications(session, message, settings)
                else:
                    process_automation(session, message, settings)
        except DBAPIError:
            raise ServiceError(503, "worker_database_unavailable") from None

    def consume_report_export(organization_id: str, job_id: str) -> None:
        try:
            org, identifier = UUID(organization_id), UUID(job_id)
        except ValueError:
            raise ServiceError(422, "invalid_report_export_message") from None
        try:
            with sessions.begin() as session:
                services = compose(session, settings=settings)
                repository = ReportExportJobRepository(session)
                job = repository.get(org, identifier)
                if job is None:
                    return
                user = services.identity.store.by_id(org, job.owner_id)
                if user is None or not user.active:
                    if job.state in {"pending", "running"}:
                        revoked = job.model_copy(
                            update={"state": "revoked", "updated_at": datetime.now(UTC)}
                        )
                        if repository.save(revoked, job.state):
                            record_export_state(
                                session,
                                org,
                                identifier,
                                job.report_id,
                                job.workspace_id,
                                "owner_inactive",
                                settings,
                                state="revoked",
                            )
                    return
                principal = Principal(issuer=user.issuer, subject=user.subject)
                actor = RequestContext(principal, uuid7(), uuid7())
                services.reporting.run_export_job(
                    actor, org, identifier, repository, services.files.storage
                )
        except ServiceError as error:
            if error.status == 503:
                raise
            with sessions.begin() as session:
                repository = ReportExportJobRepository(session)
                job = repository.get(org, identifier, lock=True)
                if job is not None and job.state in {"pending", "running"}:
                    failed = job.model_copy(
                        update={
                            "state": "failed",
                            "updated_at": datetime.now(UTC),
                            "error_code": error.code,
                        }
                    )
                    if repository.save(failed, job.state):
                        record_export_state(
                            session,
                            org,
                            identifier,
                            job.report_id,
                            job.workspace_id,
                            error.code,
                            settings,
                            state="failed",
                        )
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
    Actor(
        consume_report_export,
        broker=broker,
        actor_name="consume_report_export",
        queue_name="operations",
        priority=0,
        options={"max_retries": 0},
    )

    stop_dispatcher = Event()

    def dispatch_pending_exports() -> None:
        while not stop_dispatcher.is_set():
            try:
                with sessions.begin() as session:
                    repository = ReportExportJobRepository(session)
                    now = datetime.now(UTC)
                    pending = repository.due(now)
                    expired = repository.expired_artifacts(now)
                    expired_jobs = repository.expire_due(now)
                    for expired_job in expired_jobs:
                        record_export_state(
                            session,
                            expired_job.organization_id,
                            expired_job.id,
                            expired_job.report_id,
                            expired_job.workspace_id,
                            "job_retention",
                            settings,
                        )
                report_actor = broker.get_actor("consume_report_export")
                for organization_id, job_id in pending:
                    report_actor.send(str(organization_id), str(job_id))
                for organization_id, job_id, key in expired:
                    S3Storage(settings).delete(key)
                    with sessions.begin() as session:
                        repository = ReportExportJobRepository(session)
                        job = repository.get(organization_id, job_id, lock=True)
                        if job is not None and repository.expire(
                            organization_id, job_id, datetime.now(UTC)
                        ):
                            record_export_state(
                                session,
                                organization_id,
                                job_id,
                                job.report_id,
                                job.workspace_id,
                                "artifact_retention",
                                settings,
                            )
            except Exception:
                logging.getLogger("operations.worker").warning(
                    "report_export_dispatch_or_retention_failed"
                )
            stop_dispatcher.wait(10)

    dispatcher = Thread(
        target=dispatch_pending_exports, name="report-export-dispatcher", daemon=True
    )
    dispatcher.start()
    return WorkerRuntime(broker, actor, engine, stop_dispatcher, dispatcher)
