import os
import socketserver
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from dramatiq import Message, Worker
from operations.composition import compose
from operations.email_worker import register
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import NotifyAction, RuleDefinition
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.infrastructure.email_persistence import (
    EmailAttemptRow,
    EmailRow,
)
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.modules.projects.application.contracts import LifecycleDefinition, ProjectContext
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from operations.worker import process_automation
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_phase6_smtp import SmtpSink

pytestmark = pytest.mark.e2e


def test_committed_email_only_rule_real_redis_and_loopback_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("Retained email test database required")
        pytest.skip("Set IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://email-channel-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    SmtpSink.messages = []
    with (
        TemporaryDirectory(prefix="iop-email-channel-") as directory,
        socketserver.TCPServer(("127.0.0.1", 0), SmtpSink) as sink,
    ):
        settings = Settings(
            database_url=SecretStr(url),
            environment="test",
            email_profiles_directory=directory,
        )  # type: ignore[call-arg]
        engine = create_database_engine(settings)
        thread = threading.Thread(target=sink.serve_forever, daemon=True)
        thread.start()
        broker = register(settings, "phase6-email-channel-" + str(uuid7()))
        worker = Worker(broker, worker_threads=4)
        try:
            with Session(engine) as session, session.begin():
                services = compose(session, principal)
                services.identity.bootstrap(principal, "Retained email channel fixture")
                org = services.organizations.create(
                    actor,
                    "Email channel fixture",
                    OrganizationSettings(),
                    principal.subject,
                    "recipient@example.test",
                ).id
                workspace = services.workspaces.create(actor, org, "Email channel fixture").id
                project = services.projects.create(
                    actor,
                    org,
                    workspace,
                    "Email channel fixture",
                    ProjectContext(),
                    LifecycleDefinition(),
                ).id
                user = services.authorization.user(actor, org)
                rule = services.automation.create(
                    actor,
                    org,
                    workspace,
                    project,
                    "Email only",
                    RuleDefinition(
                        trigger="project.phase.changed",
                        actions=[
                            NotifyAction(kind="notify", recipients=[user.id], channels=["email"])
                        ],
                    ),
                )
                review = services.automation.activate(
                    actor, org, workspace, rule.id, 1, 1, True, None
                )
                services.automation.activate(
                    actor, org, workspace, rule.id, 1, 1, False, review.content_sha256
                )
                services.projects.transition(actor, org, workspace, project, "active", 1, "Begin")
                event = session.scalar(
                    select(AuditRow).where(
                        AuditRow.organization_id == org,
                        AuditRow.type == "project.transitioned",
                    )
                )
                assert event
                dispatch = DeliveryMessage(
                    organization_id=org, delivery_id=delivery_id(event.id, "automation")
                )
                assert process_automation(session, dispatch).state == "completed"
                email = session.scalar(select(EmailRow).where(EmailRow.organization_id == org))
                assert email and email.state == "pending"
                identifier = email.id
                assert services.notifications.inbox(actor, org, workspace) == ([], None)
            # Test-only credentials/profile material, outside the repository; no external mail.
            from operations.modules.notifications.infrastructure.smtp import SmtpProfile

            profile = SmtpProfile(
                organization_id=org,
                host="127.0.0.1",
                port=sink.server_address[1],
                sender="sender@example.com",
                tls=False,
                app_origin="http://localhost:5173",
            )
            Path(directory, str(org) + ".json").write_text(
                profile.model_dump_json(), encoding="utf-8"
            )
            worker.start()
            for _ in range(8):
                envelope: Message[Any] = Message(
                    queue_name="emails",
                    actor_name="consume_email",
                    args=(str(org), str(identifier)),
                    kwargs={},
                    options={},
                )
                broker.enqueue(envelope)
            broker.join("emails", timeout=15000)
            worker.join()
            assert len(SmtpSink.messages) == 1
            wire = SmtpSink.messages[0]
            assert f"Message-ID: <{identifier}@operations.invalid>".encode() in wire
            assert b"Operational notice" in wire and b"http://localhost:5173/" in wire
            assert str(project).encode() not in wire and b"payload" not in wire
            with Session(engine) as session:
                email = session.scalar(select(EmailRow).where(EmailRow.id == identifier))
                assert email and email.state == "sent" and email.attempts == 1
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(EmailAttemptRow)
                        .where(
                            EmailAttemptRow.organization_id == org,
                            EmailAttemptRow.delivery_id == identifier,
                        )
                    )
                    == 1
                )
        finally:
            worker.stop()
            broker.close()
            broker.client.close()
            sink.shutdown()
            thread.join(5)
            engine.dispose()
