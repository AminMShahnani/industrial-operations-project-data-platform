import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from dramatiq import Message, Worker
from operations.composition import compose
from operations.contracts import ServiceError
from operations.email_worker import email_service, process_email, register
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.email_contracts import EmailContent, EmailResult
from operations.modules.notifications.application.email_service import EmailService
from operations.modules.notifications.infrastructure.email_persistence import EmailAttemptRow
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


class Sink:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, EmailContent]] = []
        self.lock = threading.Lock()

    def send(self, identifier: UUID, content: EmailContent) -> EmailResult:
        with self.lock:
            self.calls.append((identifier, content))
        return EmailResult("sent")


def test_committed_workers_deduplicate_and_recover_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("Retained committed test database required")
        pytest.skip("Set IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(
        database_url=SecretStr(url), environment="test", email_profiles_directory=None
    )  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://smtp-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    engine = create_database_engine(settings)
    sink = Sink()
    try:
        with Session(engine) as session, session.begin():
            services = compose(session, principal)
            services.identity.bootstrap(principal, "Committed email fixture")
            org = services.organizations.create(
                actor,
                "Email fixture",
                OrganizationSettings(),
                principal.subject,
                "operator@example.test",
            ).id
            workspace = services.workspaces.create(actor, org, "Email fixture").id
            scope = Scope(org, ScopeType.WORKSPACE, workspace)
            identifiers = []
            for _ in range(3):
                invitation = services.identity.invite_verified_email(
                    actor, "recipient@example.test", Role.VIEWER, scope, uuid7()
                )
                delivery = email_service(session).queue(
                    actor, org, "invitation", invitation.id, None, True, "Fixture request"
                )
                identifiers.append(delivery.id)
        first, crashed, revoked = identifiers
        with pytest.raises(ServiceError, match="email_not_configured"):
            process_email(org, first, settings)
        with Session(engine) as session, session.begin():
            pending = email_service(session).store.get(org, first)
            assert pending and pending.state == "pending" and pending.attempts == 0

        broker = register(settings, "phase6-email-test-" + str(uuid7()))
        worker = Worker(broker, worker_threads=4)

        def consume(organization: UUID, delivery: UUID, configured: Settings) -> None:
            process_email(organization, delivery, configured, sink, "https://app.example.test")

        try:
            with patch("operations.email_worker.process_email", side_effect=consume):
                worker.start()
                for _ in range(8):
                    envelope: Message[Any] = Message(
                        queue_name="emails",
                        actor_name="consume_email",
                        args=(str(org), str(first)),
                        kwargs={},
                        options={},
                    )
                    assert "recipient@example.test" not in envelope.encode().decode()
                    broker.enqueue(envelope)
                broker.join("emails", timeout=15000)
                worker.join()
        finally:
            worker.stop()
            broker.close()
            broker.client.close()
        assert len(sink.calls) == 1 and sink.calls[0][0] == first

        # The provider accepted DATA but committing the attempt failed.
        with (
            patch.object(EmailService, "finish", side_effect=RuntimeError("simulated crash")),
            pytest.raises(RuntimeError, match="simulated crash"),
        ):
            process_email(org, crashed, settings, sink, "https://app.example.test")
        assert len(sink.calls) == 2
        with patch("operations.modules.notifications.application.email_service.datetime") as clock:
            clock.now.return_value = datetime.now(UTC) + timedelta(seconds=100)
            process_email(org, crashed, settings)  # Recovery needs no provider configuration.
        process_email(org, crashed, settings, sink, "https://app.example.test")
        assert len(sink.calls) == 2
        with Session(engine) as session, session.begin():
            service = email_service(session)
            current = service.store.get(org, crashed)
            assert current and current.state == "uncertain" and current.attempts == 1
            review = service.replay(actor, org, crashed)
            service.replay(actor, org, crashed, True, review.review_sha256, "Provider reviewed")
        process_email(org, crashed, settings, sink, "https://app.example.test")
        assert len(sink.calls) == 3 and sink.calls[1][0] == sink.calls[2][0] == crashed
        with Session(engine) as session, session.begin():
            service = email_service(session)
            user = service.identity.authorization.user(actor, org)
            grants = compose(session).authorization.grants.for_user(org, user.id)
            assert len(grants) == 1
            colleague = Principal(principal.issuer, str(uuid7()), "colleague@example.test", True)
            colleague_actor = RequestContext(colleague, uuid7(), uuid7())
            invitation = service.identity.invite_verified_email(
                actor,
                colleague.email or "",
                Role.ORGANIZATION_ADMIN,
                Scope(org, ScopeType.ORGANIZATION, org),
                uuid7(),
            )
            service.identity.accept_verified_email(colleague_actor, org, invitation.id)
            compose(session).authorization.revoke(colleague_actor, org, grants[0].id)
        process_email(org, revoked, settings, sink, "https://app.example.test")
        assert len(sink.calls) == 3
        with Session(engine) as session, session.begin():
            service = email_service(session)
            skipped = service.store.get(org, revoked)
            assert skipped and skipped.state == "skipped" and skipped.attempts == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EmailAttemptRow)
                    .where(EmailAttemptRow.organization_id == org)
                )
                == 4
            )
    finally:
        engine.dispose()
