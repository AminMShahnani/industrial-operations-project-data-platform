import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from dramatiq import Worker
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import (
    MetadataAction,
    RuleDefinition,
    TaskAction,
)
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.queue import DramatiqPublisher
from operations.modules.forms.application.contracts import Component, FormDefinition, Section
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.infrastructure.persistence import AttemptRow, NoticeRow
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import LifecycleDefinition, ProjectContext
from operations.modules.scheduling.application.contracts import Assignment
from operations.modules.tasks.infrastructure.persistence import TaskRow
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import register_actor
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_real_redis_workers_concurrently_deduplicate_committed_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Committed worker test needs dedicated IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    namespace = "phase6-worker-test-" + str(uuid7())
    principal = Principal("https://worker-fixture.example.test", str(uuid7()))
    context = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    runtime = register_actor(settings, namespace)
    worker = Worker(runtime.broker, worker_threads=4)
    try:
        # Retain committed fixture/audit history; never reset this database.
        with Session(engine) as session, session.begin():
            services = compose(session, principal)
            services.identity.bootstrap(principal, "Dedicated worker fixture operator")
            org = services.organizations.create(
                context,
                "Worker fixture",
                OrganizationSettings(),
                principal.subject,
                "worker-fixture@example.com",
            ).id
            workspace = services.workspaces.create(context, org, "Worker fixture").id
            project = services.projects.create(
                context, org, workspace, "Worker fixture", ProjectContext(), LifecycleDefinition()
            ).id
            form = services.forms.create(
                context,
                org,
                workspace,
                project,
                "Worker form",
                FormDefinition(
                    sections=[
                        Section(
                            key="work",
                            label="Work",
                            components=[Component(key="value", kind="integer", label="Value")],
                        )
                    ]
                ),
            )
            form_preview = services.forms.publish(
                context, org, workspace, form.id, 1, 1, True, None
            )
            services.forms.publish(
                context, org, workspace, form.id, 1, 1, False, form_preview.content_sha256
            )
            user = services.authorization.user(context, org)
            rule = services.automation.create(
                context,
                org,
                workspace,
                project,
                "Phase notice",
                RuleDefinition(
                    trigger="project.phase.changed",
                    actions=[
                        MetadataAction(kind="set_metadata", description="Worker completed"),
                        TaskAction(
                            kind="create_form_task",
                            name="Worker follow-up",
                            form_id=form.id,
                            form_number=1,
                            assignments=[Assignment(kind="user", target_id=user.id)],
                        ),
                        TaskAction(
                            kind="create_task",
                            name="Worker acknowledgement",
                            assignments=[Assignment(kind="user", target_id=user.id)],
                            due_seconds=60,
                        ),
                    ],
                ),
            )
            preview = services.automation.activate(
                context, org, workspace, rule.id, 1, 1, True, None
            )
            services.automation.activate(
                context, org, workspace, rule.id, 1, 1, False, preview.content_sha256
            )
            services.projects.transition(context, org, workspace, project, "active", 1, "begin")
            source = session.scalar(
                select(AuditRow).where(
                    AuditRow.type == "project.transitioned", AuditRow.aggregate_id == project
                )
            )
            assert source
            message = DeliveryMessage(
                organization_id=org, delivery_id=delivery_id(source.id, "automation")
            )
            source_id = source.id
        worker.start()
        publisher = DramatiqPublisher(runtime.broker)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: publisher.publish(message), range(8)))
        runtime.broker.join("operations", timeout=15000)
        worker.join()
        with Session(engine) as session:
            services = compose(session)
            row = services.projects.require_access(context, org, workspace, project, "project.read")
            assert row.context.description == "Worker completed" and row.version == 3
            run = services.automation.store.event_runs(org, source_id)[0]
            assert run.state == "completed" and run.attempts == 1
            assert len(services.automation.store.receipts(org, run.id)) == 3
            generic = session.scalars(
                select(TaskRow).where(TaskRow.organization_id == org, TaskRow.kind == "generic")
            ).all()
            assert len(generic) == 1 and generic[0].submission_id is None
            generic_id = generic[0].id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(AuditRow.organization_id == org, AuditRow.type == "project.updated")
                )
                == 1
            )
            task_source = session.scalar(
                select(AuditRow).where(
                    AuditRow.organization_id == org,
                    AuditRow.type == "task.created",
                    AuditRow.aggregate_id != generic_id,
                )
            )
            assert task_source
            notice_message = DeliveryMessage(
                organization_id=org, delivery_id=delivery_id(task_source.id, "notifications")
            )
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: publisher.publish(notice_message), range(8)))
        runtime.broker.join("operations", timeout=15000)
        worker.join()
        with Session(engine) as session:
            notice = session.scalar(select(NoticeRow).where(NoticeRow.organization_id == org))
            assert notice and notice.origin == "automatic"
            notice_id = notice.id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(NoticeRow)
                    .where(NoticeRow.organization_id == org)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AttemptRow)
                    .where(AttemptRow.organization_id == org)
                )
                == 1
            )

        def read_notice(_: int) -> str:
            with Session(engine) as session, session.begin():
                receipt = compose(session).notifications.mark_read(context, org, notice_id)
                return str(receipt.id)

        with ThreadPoolExecutor(max_workers=8) as executor:
            receipts = list(executor.map(read_notice, range(8)))
        assert len(set(receipts)) == 1

        # Separate concurrent claim and completion rounds: a completed task cannot be reclaimed.
        with ThreadPoolExecutor(max_workers=8) as executor:

            def claim_generic(_: int) -> None:
                with Session(engine) as session, session.begin():
                    compose(session).tasks.claim(context, org, workspace, generic_id, 1)

            list(executor.map(claim_generic, range(8)))
        with ThreadPoolExecutor(max_workers=8) as executor:

            def complete_generic(_: int) -> str:
                with Session(engine) as session, session.begin():
                    return str(
                        compose(session)
                        .tasks.complete(context, org, workspace, generic_id, 2)
                        .completed_at
                    )

            completions = list(executor.map(complete_generic, range(8)))
        assert len(set(completions)) == 1
        with Session(engine) as session:
            for action in ("task.claimed", "task.completed"):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditRow)
                        .where(AuditRow.aggregate_id == generic_id, AuditRow.type == action)
                    )
                    == 1
                )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditRow)
                    .where(AuditRow.organization_id == org, AuditRow.type == "notification.read")
                )
                == 1
            )
        with Session(engine) as session, session.begin():
            services = compose(session)
            services.projects.transition(
                context, org, workspace, project, "closing", 3, "Close fixture"
            )
            services.projects.transition(
                context, org, workspace, project, "closed", 4, "Close fixture"
            )
            assert len(services.notifications.inbox(context, org, workspace)[0]) == 1
            assert str(services.notifications.mark_read(context, org, notice_id).id) == receipts[0]
    finally:
        worker.stop()
        runtime.broker.flush("operations")
        runtime.close()
        engine.dispose()
