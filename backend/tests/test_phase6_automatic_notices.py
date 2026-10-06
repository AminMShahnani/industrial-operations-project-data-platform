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
from operations.modules.automation.application.events import (
    Delivery,
    DeliveryMessage,
    OperationalEvent,
)
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.notifications.application.consumer import NotificationConsumer
from operations.modules.notifications.infrastructure.persistence import AttemptRow, NoticeRow
from operations.modules.workflows.infrastructure.runtime import NotificationRow, RecipientRow
from operations.worker import process_notifications
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import publish, setup
from test_phase5_api import activate, create_workflow, definition, reviewer, submit
from test_phase6_periodic import task_fixture

pytestmark = pytest.mark.integration


def dispatch(api: Api, org: UUID, kind: str) -> DeliveryMessage:
    event = api.session.scalar(
        select(AuditRow).where(AuditRow.organization_id == org, AuditRow.type == kind)
    )
    assert event
    return DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "notifications"))


def test_task_assignment_deadline_reminder_delivery_and_duplicate_read(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    services.tasks.generate_reminders(actor, org, workspace, None, None)
    for kind in ("task.created", "task.due", "task.overdue", "task.reminder.created"):
        message = dispatch(api, org, kind)
        result = process_notifications(api.session, message)
        assert result.state == "completed" and result.attempts == 1, result
        assert process_notifications(api.session, message) == result
    items, _ = services.notifications.inbox(actor, org, workspace)
    assert len(items) == 4
    assert all(
        item.notice.origin == "automatic"
        and item.notice.run_id is None
        and item.notice.source_id == task.id
        for item in items
    )
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == 4
    read = services.notifications.mark_read(actor, org, items[0].notice.id)
    assert services.notifications.mark_read(actor, org, items[0].notice.id) == read
    for item in items:
        audit = api.session.scalar(
            select(AuditRow).where(
                AuditRow.aggregate_id == item.notice.id, AuditRow.type == "notification.created"
            )
        )
        assert audit and audit.actor_id is None
    with pytest.raises(ServiceError, match="outbox_delivery_not_found"):
        process_notifications(api.session, message.model_copy(update={"organization_id": uuid7()}))
    with pytest.raises(ServiceError, match="outbox_consumer_mismatch"):
        process_notifications(
            api.session,
            message.model_copy(
                update={"delivery_id": delivery_id(items[0].notice.event_id, "automation")}
            ),
        )


def test_workflow_review_notice_uses_exact_visit_and_revocation(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    first = reviewer(api, org, workspace)
    second = reviewer(api, org, workspace, subject="second")
    workflow = create_workflow(api, route, definition(form, [first, second]))
    activate(api, route, workflow)
    _, instance = submit(api, route, form)
    services = compose(api.session)
    # Revoke one original recipient before delivery; the eligible recipient still gets work.
    from test_phase6_actions import context

    actor, _ = context(api, org)
    grant = api.session.scalar(
        select(GrantRow).where(GrantRow.organization_id == org, GrantRow.user_id == first)
    )
    assert grant
    services.authorization.revoke(actor, org, grant.id)
    message = dispatch(api, org, "workflow.step.assigned")
    assert process_notifications(api.session, message).state == "completed"
    attempt = api.session.scalar(select(AttemptRow))
    assert attempt and attempt.created == 1 and attempt.skipped == 1
    recipient = services.identity.active_context(org, second, actor)
    items, _ = services.notifications.inbox(recipient, org, workspace)
    assert len(items) == 1 and items[0].notice.source_id == UUID(str(instance["id"]))
    assert items[0].notice.source_intent_id
    services.notifications.mark_read(recipient, org, items[0].notice.id)
    grant2 = api.session.scalar(
        select(GrantRow).where(GrantRow.organization_id == org, GrantRow.user_id == second)
    )
    assert grant2
    services.authorization.revoke(actor, org, grant2.id)
    assert services.notifications.inbox(recipient, org, workspace)[0] == []
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 1
    assert process_notifications(api.session, message).attempts == 1


def test_notify_node_notice_without_review_or_submission_access(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    recipient_id = reviewer(api, org, workspace)
    body = {
        "form_id": form,
        "form_number": 1,
        "nodes": [
            {"key": "start", "name": "Start", "kind": "start"},
            {
                "key": "notice",
                "name": "Notice",
                "kind": "notify",
                "assignments": [{"kind": "user", "target_id": str(recipient_id)}],
            },
            {"key": "end", "name": "End", "kind": "end"},
        ],
        "transitions": [
            {"source": "start", "target": "notice"},
            {"source": "notice", "target": "end"},
        ],
    }
    workflow = create_workflow(api, route, body)
    activate(api, route, workflow)
    submission, instance = submit(api, route, form)
    intent = api.session.scalar(select(NotificationRow))
    assert intent
    services = compose(api.session)
    from test_phase6_actions import context

    actor, _ = context(api, org)
    recipient = services.identity.active_context(org, recipient_id, actor)
    with pytest.raises(ServiceError, match="workflow_private"):
        services.workflow_runtime.access(recipient, org, workspace, UUID(str(instance["id"])))
    with pytest.raises(ServiceError, match="submission_private"):
        services.submissions.access(recipient, org, workspace, UUID(submission))
    message = dispatch(api, org, "workflow.notification.requested")
    assert process_notifications(api.session, message).state == "completed"
    item = services.notifications.inbox(recipient, org, workspace)[0][0]
    assert item.notice.source_intent_id == intent.id and item.notice.topic == "rule_notice"
    services.notifications.mark_read(recipient, org, item.notice.id)
    assert api.session.scalar(select(func.count()).select_from(RecipientRow)) == 0


def test_transient_notice_failure_rolls_back_all_effects_and_retries_once(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")
    original = NotificationConsumer.deliver

    def fail_after_delivery(
        self: NotificationConsumer, delivery: Delivery, source: OperationalEvent
    ) -> tuple[int, int]:
        original(self, delivery, source)
        raise ServiceError(503, "fixture_notification_transient")

    monkeypatch.setattr(NotificationConsumer, "deliver", fail_after_delivery)
    result = process_notifications(api.session, message)
    assert result.state == "retry" and result.attempts == 1
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(AuditRow.type == "notification.created")
        )
        == 0
    )
    assert process_notifications(api.session, message) == result
    monkeypatch.setattr(NotificationConsumer, "deliver", original)
    compose(api.session).automation.complete_notification_delivery(
        result.model_copy(update={"next_at": datetime.now(UTC) - timedelta(seconds=1)})
    )
    result = process_notifications(api.session, message)
    assert result.state == "completed" and result.attempts == 2
    assert len(compose(api.session).notifications.inbox(actor, org, workspace)[0]) == 1
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == 2


def test_automatic_notice_evidence_and_populated_rollback_are_guarded(api: Api) -> None:
    actor, org, workspace, _ = task_fixture(api)
    process_notifications(api.session, dispatch(api, org, "task.created"))
    notice = compose(api.session).notifications.inbox(actor, org, workspace)[0][0].notice
    for sql in (
        "UPDATE notification_attempts SET number=number",
        "DELETE FROM notification_attempts",
        "TRUNCATE notification_attempts",
        "UPDATE notifications SET origin='automation'",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
    with pytest.raises(DBAPIError), api.session.begin_nested():
        compose(api.session).notifications.store.add(
            notice.model_copy(update={"id": uuid7(), "source_id": uuid7()})
        )
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("a5fa16a227ff")
    assert revision
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()


@pytest.mark.parametrize("status,maximum", [(503, 8), (422, 1)])
def test_notification_failure_bounds_and_terminal_redelivery(
    api: Api, monkeypatch: pytest.MonkeyPatch, status: int, maximum: int
) -> None:
    _, org, _, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")

    def fail(
        self: NotificationConsumer, delivery: Delivery, source: OperationalEvent
    ) -> tuple[int, int]:
        raise ServiceError(status, "fixture_notification_failure")

    monkeypatch.setattr(NotificationConsumer, "deliver", fail)
    services = compose(api.session)
    for number in range(1, maximum + 1):
        result = process_notifications(api.session, message)
        assert result.attempts == number
        assert result.state == ("dead_letter" if number == maximum else "retry")
        if result.state == "retry":
            assert result.next_at > datetime.now(UTC)
            services.automation.complete_notification_delivery(
                result.model_copy(update={"next_at": datetime.now(UTC) - timedelta(seconds=1)})
            )
    assert process_notifications(api.session, message) == result
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == maximum
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
