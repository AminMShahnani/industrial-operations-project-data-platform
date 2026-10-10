from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import (
    AutomationAction,
    NotifyAction,
    Rule,
    RuleDefinition,
    Run,
)
from operations.modules.automation.application.events import DeliveryMessage, OperationalEvent
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.notifications.application.service import NotificationService
from operations.modules.notifications.infrastructure.persistence import NoticeRow, ReadRow
from operations.worker import process_automation
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase3_api import draft, publish, setup
from test_phase5_api import reviewer
from test_phase6_actions import activate, context
from test_phase6_periodic import task_fixture

pytestmark = pytest.mark.integration


def message(api: Api, org: UUID, kind: str) -> DeliveryMessage:
    source = api.session.scalar(
        select(AuditRow).where(AuditRow.organization_id == org, AuditRow.type == kind)
    )
    assert source
    return DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))


def test_notice_delivery_duplicate_read_evidence_and_minimal_contents(api: Api) -> None:
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
            actions=[NotifyAction(kind="notify", recipients=[user])],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin")
    dispatch = message(api, org, "project.transitioned")
    assert process_automation(api.session, dispatch).state == "completed"
    assert process_automation(api.session, dispatch).state == "completed"
    items, cursor = services.notifications.inbox(actor, org, workspace)
    assert len(items) == 1 and cursor is None and items[0].read_at is None
    notice = items[0].notice
    assert notice.source_id == identifier and notice.source_kind == "project"
    assert not {"payload", "values", "email", "body", "name"} & set(notice.model_dump())
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}/notifications"
    assert api.client.get(route).status_code == 401
    result = api.client.get(route, headers=api.headers("admin"))
    assert result.json()["items"][0]["notice"]["id"] == str(notice.id)
    read_response = api.client.post(route + f"/{notice.id}/read", headers=api.headers("admin"))
    assert read_response.status_code == 200, read_response.text
    read = services.notifications.mark_read(actor, org, notice.id)
    assert services.notifications.mark_read(actor, org, notice.id) == read
    assert services.notifications.inbox(actor, org, workspace)[0][0].read_at == read.read_at
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 1
    assert api.session.scalar(select(func.count()).select_from(ReadRow)) == 1
    created = api.session.scalar(select(AuditRow).where(AuditRow.type == "notification.created"))
    assert created and created.payload["run_id"] == str(notice.run_id)
    assert created.payload["authorization_kind"] == "delegated_automation"
    assert (
        api.session.scalar(
            select(func.count()).select_from(AuditRow).where(AuditRow.type == "notification.read")
        )
        == 1
    )
    other = reviewer(api, org, workspace, role="Viewer")
    other_actor = services.identity.active_context(org, other, actor)
    assert (
        api.client.get(route + f"/{notice.id}", headers=api.headers("reviewer")).status_code == 404
    )
    with pytest.raises(ServiceError, match="notification_not_found"):
        services.notifications.mark_read(other_actor, org, notice.id)
    with pytest.raises(ServiceError):
        services.notifications.mark_read(actor, uuid7(), notice.id)
    assert services.notifications.inbox(actor, org, api.workspace(org))[0] == []


def test_private_draft_notice_recipient_denied_and_whole_run_rolled_back(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    actor, owner = context(api, org)
    other = reviewer(api, org, workspace, role="Viewer")
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="submission.created",
            actions=[
                NotifyAction(kind="notify", recipients=[owner]),
                NotifyAction(kind="notify", recipients=[owner, other]),
            ],
        ),
    )
    draft(api, route, form)
    dispatch = message(api, org, "submission.draft.created")
    assert process_automation(api.session, dispatch).state == "dead_letter"
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(AuditRow.type == "notification.created")
        )
        == 0
    )
    source = api.session.scalar(
        select(AuditRow.id).where(AuditRow.type == "submission.draft.created")
    )
    assert source
    run = compose(api.session).automation.store.event_runs(org, source)[0]
    assert run.error_code == "submission_private"
    assert compose(api.session).automation.store.receipts(org, run.id) == []


def test_submitted_notice_and_revoked_scope_hidden_without_deletion(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    owner = reviewer(api, org, workspace, subject="operator", role="WorkspaceAdmin")
    actor, _ = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="submission.submitted",
            actions=[NotifyAction(kind="notify", recipients=[owner])],
        ),
    )
    # Use a submitted source: the delegated administrator cannot read another owner's draft.
    submission = draft(api, route, form)
    services = compose(api.session)
    from operations.modules.forms.application.contracts import FormValues

    saved = services.submissions.save(
        actor, org, workspace, UUID(submission), FormValues(fields={"quantity": 2}), 1
    )
    services.submissions.submit(
        actor, org, workspace, UUID(submission), saved.revision, uuid7(), "submit"
    )
    assert (
        process_automation(api.session, message(api, org, "submission.submitted")).state
        == "completed"
    )
    recipient = services.identity.active_context(org, owner, actor)
    items, _ = services.notifications.inbox(recipient, org, workspace)
    assert len(items) == 1
    grant = api.session.scalar(
        select(GrantRow).where(GrantRow.organization_id == org, GrantRow.user_id == owner)
    )
    assert grant
    services.authorization.revoke(actor, org, grant.id)
    assert services.notifications.inbox(recipient, org, workspace)[0] == []
    with pytest.raises(ServiceError):
        services.notifications.mark_read(recipient, org, items[0].notice.id)
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 1


def test_task_notice_uses_original_assignment_and_hides_claimed_draft(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    user = services.authorization.user(actor, org)
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="task.due",
            actions=[NotifyAction(kind="notify", recipients=[user.id], topic="work_assigned")],
        ),
    )
    claimed = services.tasks.claim(actor, org, workspace, task.id, 1)
    assert claimed.submission_id
    services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    assert process_automation(api.session, message(api, org, "task.due")).state == "completed"
    notice = services.notifications.inbox(actor, org, workspace)[0][0].notice
    assert notice.source_kind == "task" and notice.source_id == task.id
    assert str(claimed.submission_id) not in notice.model_dump_json()
    other = reviewer(api, org, workspace, role="Contributor")
    other_actor = services.identity.active_context(org, other, actor)
    with pytest.raises(ServiceError, match="task_not_assigned"):
        services.notifications.sources.require(other_actor, org, workspace, None, "task", task.id)


def test_notice_immutability_forgery_and_populated_rollback(api: Api) -> None:
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
            actions=[NotifyAction(kind="notify", recipients=[user])],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin")
    process_automation(api.session, message(api, org, "project.transitioned"))
    notice = services.notifications.inbox(actor, org, workspace)[0][0].notice
    services.notifications.mark_read(actor, org, notice.id)
    for table in ("notifications", "notification_reads"):
        for sql in (
            f"UPDATE {table} SET id=id",
            f"DELETE FROM {table}",
            f"TRUNCATE {table} CASCADE",
        ):
            with pytest.raises(DBAPIError), api.session.begin_nested():
                api.session.execute(text(sql))
    forged = notice.model_copy(update={"id": uuid7(), "source_id": uuid7()})
    with pytest.raises(DBAPIError), api.session.begin_nested():
        services.notifications.store.add(forged)
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("73eddd554d17")
    assert revision
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()


def test_notification_channels_and_duplicate_recipients_fail_closed(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    for action in (
        NotifyAction(kind="notify", recipients=[user], channels=["email", "email"]),
        NotifyAction(kind="notify", recipients=[user, user]),
    ):
        with pytest.raises(ServiceError):
            activate(
                api,
                actor,
                org,
                workspace,
                None,
                RuleDefinition(trigger="submission.created", actions=[action]),
            )


def test_notice_chronological_paging(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, user = context(api, org)
    # Six rules * twenty actions create 120 UUIDv5 notices in one source transaction.
    for _ in range(6):
        activate(
            api,
            actor,
            org,
            workspace,
            identifier,
            RuleDefinition(
                trigger="project.phase.changed",
                actions=[NotifyAction(kind="notify", recipients=[user]) for _ in range(20)],
            ),
        )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin")
    dispatch = message(api, org, "project.transitioned")
    assert process_automation(api.session, dispatch).state == "completed"
    first, cursor = services.notifications.inbox(actor, org, workspace)
    assert len(first) == 100 and cursor
    second, next_cursor = services.notifications.inbox(actor, org, workspace, cursor)
    assert len(second) == 20 and next_cursor is None
    all_notices = [item.notice for item in first + second]
    assert len({item.id for item in all_notices}) == 120
    assert [(item.created_at, item.id) for item in all_notices] == sorted(
        (item.created_at, item.id) for item in all_notices
    )
    with pytest.raises(ServiceError, match="notification_cursor_invalid"):
        services.notifications.inbox(actor, org, workspace, uuid7())


def test_notification_transient_retry_rolls_back_all_effects(
    api: Api, monkeypatch: pytest.MonkeyPatch
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
            actions=[NotifyAction(kind="notify", recipients=[user]) for _ in range(2)],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin")
    dispatch = message(api, org, "project.transitioned")
    original = NotificationService.execute

    def fail_second(
        self: NotificationService,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None:
        if position == 1:
            raise ServiceError(503, "fixture_notification_transient")
        return original(self, actor, rule, event, run, position, action)

    monkeypatch.setattr(NotificationService, "execute", fail_second)
    assert process_automation(api.session, dispatch).state == "retry"
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(AuditRow.type == "notification.created")
        )
        == 0
    )
    delivery = services.automation.store.delivery(org, dispatch.delivery_id)
    assert delivery
    run = services.automation.store.event_runs(org, delivery.event_id)[0]
    assert services.automation.store.receipts(org, run.id) == []
    monkeypatch.setattr(NotificationService, "execute", original)
    due = datetime.now(UTC) - timedelta(seconds=1)
    services.automation.store.save_run(run.model_copy(update={"next_at": due}))
    services.automation.store.save_delivery(delivery.model_copy(update={"next_at": due}))
    assert process_automation(api.session, dispatch).state == "completed"
    assert process_automation(api.session, dispatch).state == "completed"
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 2
    assert len(services.automation.store.receipts(org, run.id)) == 2
