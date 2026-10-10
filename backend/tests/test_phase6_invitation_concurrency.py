import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid7

import pytest
from alembic import command
from alembic.config import Config
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.organizations.application.contracts import OrganizationSettings
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.e2e


def test_committed_invitation_retries_and_acceptance_create_one_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("IOP_BROWSER_DATABASE_URL")
    if not url:
        pytest.skip("Committed invitation test needs IOP_BROWSER_DATABASE_URL")
    assert url.rsplit("/", 1)[-1].endswith("_browser_test")
    settings = Settings(database_url=SecretStr(url), environment="test")  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    principal = Principal("https://invitation-fixture.example.test", str(uuid7()))
    actor = RequestContext(principal, uuid7(), uuid7())
    invitee = Principal(principal.issuer, str(uuid7()), "invitation-fixture@example.test", True)
    recipient = RequestContext(invitee, uuid7(), uuid7())
    identifier = uuid7()
    engine = create_database_engine(settings)
    try:
        # Retain all fixture/audit history in this dedicated database.
        with Session(engine) as session, session.begin():
            service = compose(session, principal)
            service.identity.bootstrap(principal, "Committed invitation fixture")
            org = service.organizations.create(
                actor,
                "Invitation fixture",
                OrganizationSettings(),
                principal.subject,
                "inviter-fixture@example.test",
            ).id
            workspace = service.workspaces.create(actor, org, "Invitation fixture").id
        scope = Scope(org, ScopeType.WORKSPACE, workspace)

        def create() -> str:
            with Session(engine) as session, session.begin():
                return str(
                    compose(session, principal)
                    .identity.invite_verified_email(
                        actor, "invitation-fixture@example.test", Role.VIEWER, scope, identifier
                    )
                    .id
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: create(), range(8))) == [str(identifier)] * 8

        def accept() -> bool:
            try:
                with Session(engine) as session, session.begin():
                    compose(session, invitee).identity.accept_verified_email(
                        recipient, org, identifier
                    )
                return True
            except ServiceError as error:
                assert error.status == 403 and error.code == "invalid_invitation"
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(lambda _: accept(), range(8))) == 1
        with Session(engine) as session, session.begin():
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(GrantRow)
                    .where(GrantRow.organization_id == org, GrantRow.scope_id == workspace)
                )
                == 1
            )
            for kind in ("identity.invitation.email_created", "identity.invitation.accepted"):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditRow)
                        .where(
                            AuditRow.organization_id == org,
                            AuditRow.aggregate_id == identifier,
                            AuditRow.type == kind,
                        )
                    )
                    == 1
                )
    finally:
        engine.dispose()
