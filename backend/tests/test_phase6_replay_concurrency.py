import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.consumer import NotificationConsumer
from operations.modules.notifications.infrastructure.persistence import AttemptRow
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import LifecycleDefinition, ProjectContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_notifications
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_committed_concurrent_replays_apply_one_review_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Committed replay test needs dedicated IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://replay-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        # Retain committed fixture/audit history; never reset this database.
        with Session(engine) as session, session.begin():
            services = compose(session, principal)
            services.identity.bootstrap(principal, "Dedicated replay fixture operator")
            org = services.organizations.create(
                actor,
                "Replay fixture",
                OrganizationSettings(),
                principal.subject,
                "replay-fixture@example.test",
            ).id
            workspace = services.workspaces.create(actor, org, "Replay fixture").id
            project = services.projects.create(
                actor, org, workspace, "Replay fixture", ProjectContext(), LifecycleDefinition()
            ).id
            services.projects.transition(actor, org, workspace, project, "active", 1, "Fixture")
            event = session.scalar(
                select(AuditRow).where(
                    AuditRow.organization_id == org, AuditRow.type == "project.transitioned"
                )
            )
            assert event
            message = DeliveryMessage(
                organization_id=org, delivery_id=delivery_id(event.id, "notifications")
            )

            def fail(*args: object) -> tuple[int, int]:
                raise ServiceError(503, "test_adapter_unavailable")

            with monkeypatch.context() as patch:
                patch.setattr(NotificationConsumer, "deliver", fail)
                assert process_notifications(session, message).state == "retry"
            preview = services.automation.replay_notification(
                actor, org, workspace, message.delivery_id
            )

        tenant_locked, allow_identity, caller_started = Event(), Event(), Event()
        application_name = "identity-lock-test-" + str(uuid7())

        def organization_then_identity() -> None:
            with Session(engine) as session, session.begin():
                services = compose(session)
                services.organizations.active(org)
                tenant_locked.set()
                assert allow_identity.wait(10)
                assert services.authorization.user(actor, org).active

        def identity_then_organization() -> None:
            assert tenant_locked.wait(10)
            with Session(engine) as session, session.begin():
                session.execute(
                    text("SELECT set_config('application_name', :name, true)"),
                    {"name": application_name},
                )
                caller_started.set()
                services = compose(session)
                assert services.authorization.user(actor, org).active
                services.organizations.active(org)

        # Force the formerly inverted order using committed, independent sessions.
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(organization_then_identity)
            second = executor.submit(identity_then_organization)
            try:
                assert caller_started.wait(10)
                deadline = time.monotonic() + 5
                waiting = False
                while time.monotonic() < deadline:
                    with engine.connect() as connection:
                        waiting = bool(
                            connection.scalar(
                                text(
                                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                    "WHERE application_name=:name AND wait_event_type='Lock')"
                                ),
                                {"name": application_name},
                            )
                        )
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting, "Independent identity caller must contend on the held tenant"
            finally:
                allow_identity.set()
            first.result(timeout=10)
            second.result(timeout=10)

        def replay(_: int) -> str:
            with Session(engine) as session, session.begin():
                try:
                    result = compose(session).automation.replay_notification(
                        actor,
                        org,
                        workspace,
                        message.delivery_id,
                        dry_run=False,
                        review_sha256=preview.review_sha256,
                        reason="Concurrent repair request",
                    )
                    assert result.applied and result.delivery.attempts == 1
                    return "applied"
                except ServiceError as error:
                    assert error.code == "notification_replay_review_required"
                    return "stale"

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(replay, range(8)))
        assert results.count("applied") == 1 and results.count("stale") == 7
        with Session(engine) as session, session.begin():
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(
                        AuditRow.organization_id == org,
                        AuditRow.type == "outbox.notification.replayed",
                    )
                )
                == 1
            )
            assert process_notifications(session, message).state == "completed"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AttemptRow)
                    .where(AttemptRow.organization_id == org)
                )
                == 2
            )
    finally:
        engine.dispose()
