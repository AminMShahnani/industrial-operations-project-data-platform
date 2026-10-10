from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx2 import Response
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import NotifyAction, RuleDefinition
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.identity.infrastructure.persistence import InvitationRow
from operations.modules.notifications.application.email_contracts import EmailDelivery, EmailKind
from operations.modules.notifications.application.email_service import EmailService
from operations.modules.notifications.infrastructure.email_persistence import EmailRow
from operations.modules.notifications.infrastructure.persistence import NoticeRow, ReadRow
from operations.worker import process_automation
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase5_api import reviewer
from test_phase6_actions import activate, context
from test_phase6_notifications import message

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "channels", [["in_app"], ["email"], ["in_app", "email"], ["email", "in_app"]]
)
def test_activated_channels_capture_atomic_minimal_intent(
    api: Api, channels: list[Literal["in_app", "email"]]
) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, user = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="project.phase.changed",
            actions=[NotifyAction(kind="notify", recipients=[user], channels=channels)],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "Begin")
    dispatch = message(api, org, "project.transitioned")
    assert process_automation(api.session, dispatch).state == "completed"
    assert process_automation(api.session, dispatch).state == "completed"
    notice = api.session.scalar(select(NoticeRow).where(NoticeRow.organization_id == org))
    assert notice and notice.in_app == ("in_app" in channels)
    items, cursor = services.notifications.inbox(actor, org, workspace)
    assert len(items) == int(notice.in_app) and cursor is None
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}/notifications/{notice.id}"
    assert api.client.get(route, headers=api.headers("admin")).status_code == (
        200 if notice.in_app else 404
    )
    if not notice.in_app:
        assert api.client.post(route + "/read", headers=api.headers("admin")).status_code == 404
        with pytest.raises(ServiceError, match="notification_cursor_invalid"):
            services.notifications.inbox(actor, org, workspace, notice.id)
        value = services.notifications.store.get(org, user, notice.id)
        assert value
        with pytest.raises(DBAPIError), api.session.begin_nested():
            services.notifications.audit(actor, value, "notification.read")
            api.session.add(
                ReadRow(
                    id=uuid7(),
                    organization_id=org,
                    recipient_id=user,
                    notice_id=notice.id,
                    read_at=notice.created_at,
                )
            )
            api.session.flush()
    email = api.session.scalar(select(EmailRow).where(EmailRow.organization_id == org))
    assert bool(email) == ("email" in channels)
    if email:
        assert (
            email.source_id == notice.id
            and email.recipient_id == user
            and email.operator_id == user
        )
        delivery = services.email.store.get(org, email.id)
        assert delivery
        assert (
            services.email.render(delivery, "https://app.example.test").recipient
            == "admin@example.com"
        )
        assert "admin@example.com" not in delivery.model_dump_json()
        assert (
            api.session.scalar(
                select(func.count())
                .select_from(AuditRow)
                .where(
                    AuditRow.type == "email.queued",
                    AuditRow.aggregate_id == email.id,
                )
            )
            == 1
        )
        api.session.execute(
            update(GrantRow)
            .where(
                GrantRow.organization_id == org,
                GrantRow.user_id == user,
            )
            .values(revoked=True)
        )
        with pytest.raises(ServiceError):
            services.email.render(delivery, "https://app.example.test")


def test_email_capture_failure_rolls_back_entire_multi_action_run(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, user = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="project.phase.changed",
            actions=[
                NotifyAction(kind="notify", recipients=[user], channels=["in_app", "email"])
                for _ in range(2)
            ],
        ),
    )
    compose(api.session).projects.transition(
        actor, org, workspace, identifier, "active", 1, "Begin"
    )
    original = EmailService.queue
    calls = 0

    def queue(
        self: EmailService,
        actor: RequestContext,
        org: UUID,
        kind: EmailKind,
        source: UUID,
        recipient: UUID | None,
        apply: bool = False,
        reason: str | None = None,
    ) -> EmailDelivery:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ServiceError(503, "fixture_capture_failure")
        return original(self, actor, org, kind, source, recipient, apply, reason)

    with patch.object(EmailService, "queue", queue):
        result = process_automation(api.session, message(api, org, "project.transitioned"))
    assert result.state == "retry"
    assert api.session.scalar(select(func.count()).select_from(EmailRow)) == 0
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(
                AuditRow.type.in_(["email.queued", "notification.created"]),
            )
        )
        == 0
    )


def request(
    api: Api,
    org: UUID,
    workspace: UUID,
    identifier: UUID,
    email_delivery: bool = True,
    email_reason: str = "Requested sign-in invitation",
) -> Response:
    return api.client.post(
        f"/api/v1/organizations/{org}/invitations/verified-email",
        headers=api.headers("admin"),
        json={
            "id": str(identifier),
            "email": "invitee@example.com",
            "role": "Viewer",
            "scope_type": "workspace",
            "scope_id": str(workspace),
            "email_delivery": email_delivery,
            "email_reason": email_reason,
        },
    )


def test_invitation_email_api_atomic_dedup_and_manual_default(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = uuid7()
    for _ in range(2):
        response = request(api, org, workspace, identifier)
        assert response.status_code == 201
    assert api.session.scalar(select(func.count()).select_from(EmailRow)) == 1
    assert api.session.scalar(select(func.count()).select_from(InvitationRow)) == 1
    assert request(api, org, workspace, uuid7(), email_delivery=False).status_code == 201
    assert api.session.scalar(select(func.count()).select_from(EmailRow)) == 1
    assert request(api, org, workspace, uuid7(), email_reason=" ").status_code == 422
    assert api.session.scalar(select(func.count()).select_from(InvitationRow)) == 2


def test_invitation_email_capture_failure_rolls_back_source(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    with patch.object(
        EmailService, "queue", side_effect=ServiceError(503, "fixture_capture_failure")
    ):
        assert request(api, org, workspace, uuid7()).status_code == 503
    assert api.session.scalar(select(func.count()).select_from(EmailRow)) == 0
    assert api.session.scalar(select(func.count()).select_from(InvitationRow)) == 0


def test_workspace_admin_cannot_delegate_email(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    user = reviewer(api, org, workspace, role="WorkspaceAdmin")
    actor, _ = context(api, org)
    restricted = compose(api.session).identity.active_context(org, user, actor)
    scope = Scope(org, ScopeType.WORKSPACE, workspace)
    with pytest.raises(ServiceError):
        compose(api.session).email.invite(
            restricted, "invitee@example.com", Role.VIEWER, scope, uuid7(), True, "Denied"
        )
    assert api.session.scalar(select(func.count()).select_from(InvitationRow)) == 1


def test_email_channel_version_blocks_populated_downgrade(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="submission.created",
            actions=[NotifyAction(kind="notify", recipients=[user], channels=["email"])],
        ),
    )
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("5caef6ad5721")
    assert revision
    with (
        Operations.context(MigrationContext.configure(api.session.connection())),
        pytest.raises(RuntimeError, match="Email channel evidence exists"),
    ):
        revision.module.downgrade()
