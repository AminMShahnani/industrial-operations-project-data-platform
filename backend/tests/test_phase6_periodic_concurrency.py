import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, tzinfo
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.modules.automation.application import service as automation_module
from operations.modules.automation.application.contracts import MetadataAction, RuleDefinition
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.timers import TimerOccurrenceRow
from operations.modules.forms.application.contracts import Component, FormDefinition, Section
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import LifecycleDefinition, ProjectContext
from operations.modules.scheduling.application.contracts import (
    Assignment,
    Recurrence,
    ScheduleDefinition,
)
from operations.modules.tasks.infrastructure.persistence import DeadlineRow, TaskRow
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_automation
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_concurrent_committed_timer_and_deadline_ticks_emit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Committed periodic test needs dedicated IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://periodic-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=4)

    class ActivationClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> ActivationClock:
            return cls.fromtimestamp((start + timedelta(seconds=30)).timestamp(), UTC)

    try:
        # Dedicated committed fixtures retain all operational/audit history.
        with Session(engine) as session, session.begin():
            services = compose(session, principal, settings)
            services.identity.bootstrap(principal, "Periodic concurrency fixture")
            org = services.organizations.create(
                actor,
                "Periodic fixture",
                OrganizationSettings(),
                principal.subject,
                "periodic-fixture@example.com",
            ).id
            workspace = services.workspaces.create(actor, org, "Periodic fixture").id
            project = services.projects.create(
                actor, org, workspace, "Periodic fixture", ProjectContext(), LifecycleDefinition()
            ).id
            form = services.forms.create(
                actor,
                org,
                workspace,
                project,
                "Periodic fixture",
                FormDefinition(
                    sections=[
                        Section(
                            key="main",
                            label="Main",
                            components=[Component(key="note", kind="text", label="Note")],
                        )
                    ]
                ),
            )
            preview = services.forms.publish(actor, org, workspace, form.id, 1, 1, True, None)
            services.forms.publish(
                actor, org, workspace, form.id, 1, 1, False, preview.content_sha256
            )
            user = services.authorization.user(actor, org)
            schedule = services.scheduling.create(
                actor,
                org,
                workspace,
                project,
                "Deadline fixture",
                ScheduleDefinition(
                    form_id=form.id,
                    form_number=1,
                    recurrence=Recurrence(kind="one_time", at=start),
                    assignments=[Assignment(kind="user", target_id=user.id)],
                    due_after_seconds=0,
                ),
            )
            preview_schedule = services.scheduling.activate(
                actor, org, workspace, schedule.id, 1, 1, True, None
            )
            services.scheduling.activate(
                actor, org, workspace, schedule.id, 1, 1, False, preview_schedule.content_sha256
            )
            services.tasks.materialize(
                actor, org, workspace, schedule.id, start, start + timedelta(seconds=1), False
            )
            rule = services.automation.create(
                actor,
                org,
                workspace,
                project,
                "Timer fixture",
                RuleDefinition(
                    trigger="scheduled.timer",
                    timer_start=start,
                    timer_seconds=60,
                    actions=[
                        MetadataAction(kind="set_metadata", description="Periodic worker completed")
                    ],
                ),
            )
            preview_rule = services.automation.activate(
                actor, org, workspace, rule.id, 1, 1, True, None
            )
            with monkeypatch.context() as patch:
                patch.setattr(automation_module, "datetime", ActivationClock)
                services.automation.activate(
                    actor, org, workspace, rule.id, 1, 1, False, preview_rule.content_sha256
                )
        cutoff = start + timedelta(seconds=120)

        def timer_tick(_: int) -> int:
            with Session(engine) as session, session.begin():
                services = compose(session, principal, settings)
                timers = services.timers.tick(actor, org, workspace, rule.id, False, now=cutoff)
                return timers.created

        def deadline_tick(_: int) -> int:
            with Session(engine) as session, session.begin():
                deadlines = compose(session, principal, settings).tasks.generate_deadlines(
                    actor, org, workspace, project, dry_run=False
                )
                return deadlines.created

        with Session(engine) as locked:
            locked.scalar(select(TaskRow).where(TaskRow.organization_id == org).with_for_update())
            assert deadline_tick(0) == 0
            locked.rollback()

        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(timer_tick, range(8))) == 2
            assert sum(executor.map(deadline_tick, range(8))) == 2
        with Session(engine) as session, session.begin():
            rows = session.scalars(
                select(TimerOccurrenceRow).where(TimerOccurrenceRow.organization_id == org)
            ).all()
            assert len(rows) == 2
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DeadlineRow)
                    .where(DeadlineRow.organization_id == org)
                )
                == 2
            )
            task = session.scalar(select(TaskRow).where(TaskRow.organization_id == org))
            assert task and task.state == "open" and task.revision == 1
            for row in rows:
                message = DeliveryMessage(
                    organization_id=org, delivery_id=delivery_id(row.id, "automation")
                )
                assert process_automation(session, message, settings).state == "completed"
                assert process_automation(session, message, settings).state == "completed"
            target = compose(session, principal, settings).projects.require_access(
                actor, org, workspace, project, "project.read"
            )
            assert target.context.description == "Periodic worker completed" and target.version == 3
    finally:
        engine.dispose()
