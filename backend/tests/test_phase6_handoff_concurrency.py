import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.forms.application.contracts import Component, FormDefinition, Section
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.reconciliation import NotificationReconciler
from operations.modules.notifications.infrastructure.persistence import AttemptRow, NoticeRow
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.scheduling.application.contracts import (
    Assignment,
    Recurrence,
    ScheduleDefinition,
)
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_notifications
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_committed_concurrent_handoff_and_delivery_produce_one_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Committed handoff test needs dedicated IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://handoff-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    try:
        # Retain committed fixture/audit history; never reset this database.
        with Session(engine) as session, session.begin():
            services = compose(session, principal)
            services.identity.bootstrap(principal, "Dedicated handoff fixture operator")
            org = services.organizations.create(
                actor,
                "Handoff fixture",
                OrganizationSettings(),
                principal.subject,
                "handoff-fixture@example.test",
            ).id
            workspace = services.workspaces.create(actor, org, "Handoff fixture").id
            form = services.forms.create(
                actor,
                org,
                workspace,
                None,
                "Handoff form",
                FormDefinition(
                    sections=[
                        Section(
                            key="work",
                            label="Work",
                            components=[Component(key="value", kind="integer", label="Value")],
                        )
                    ],
                ),
            )
            publication = services.forms.publish(actor, org, workspace, form.id, 1, 1, True, None)
            services.forms.publish(
                actor, org, workspace, form.id, 1, 1, False, publication.content_sha256
            )
            start = datetime.now(UTC) - timedelta(hours=1)
            schedule = services.scheduling.create(
                actor,
                org,
                workspace,
                None,
                "Handoff fixture",
                ScheduleDefinition(
                    form_id=form.id,
                    form_number=1,
                    recurrence=Recurrence(kind="one_time", at=start),
                    assignments=[
                        Assignment(
                            kind="user", target_id=services.authorization.user(actor, org).id
                        )
                    ],
                    due_after_seconds=0,
                    reminder_offsets=[0],
                ),
            )
            activation = services.scheduling.activate(
                actor, org, workspace, schedule.id, 1, 1, True, None
            )
            services.scheduling.activate(
                actor, org, workspace, schedule.id, 1, 1, False, activation.content_sha256
            )
            services.tasks.materialize(
                actor, org, workspace, schedule.id, start, start + timedelta(seconds=1), False
            )
            capture = services.automation.audit.capture
            try:
                services.automation.audit.capture = None
                assert services.tasks.generate_reminders(actor, org, workspace, None, None)[0] == 1
            finally:
                services.automation.audit.capture = capture
            preview = NotificationReconciler(
                services.automation, services.tasks, services.workflow_runtime
            ).reconcile(actor, org, workspace, "task_reminder")
            assert len(preview.items) == 1 and preview.items[0].existing_event_id is None

        def apply(_: int) -> str:
            with Session(engine) as session, session.begin():
                services = compose(session)
                try:
                    result = NotificationReconciler(
                        services.automation, services.tasks, services.workflow_runtime
                    ).reconcile(
                        actor,
                        org,
                        workspace,
                        "task_reminder",
                        dry_run=False,
                        review_sha256=preview.review_sha256,
                        reason="Reviewed committed recovery",
                    )
                    assert result.created == 1
                    return "created"
                except ServiceError as error:
                    assert error.code == "notification_handoff_review_required"
                    return "stale"

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(apply, range(8)))
        assert outcomes.count("created") == 1 and outcomes.count("stale") == 7
        message = DeliveryMessage(
            organization_id=org,
            delivery_id=delivery_id(preview.items[0].intent_id, "notifications"),
        )

        def deliver(_: int) -> None:
            with Session(engine) as session, session.begin():
                assert process_notifications(session, message).state == "completed"

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(deliver, range(8)))
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(
                        AuditRow.organization_id == org,
                        AuditRow.type == "notification.handoff.reconciled",
                    )
                )
                == 1
            )
            for model in (NoticeRow, AttemptRow):
                assert (
                    session.scalar(
                        select(func.count()).select_from(model).where(model.organization_id == org)
                    )
                    == 1
                )
    finally:
        engine.dispose()
