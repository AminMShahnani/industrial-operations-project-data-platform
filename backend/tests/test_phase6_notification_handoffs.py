from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditEvent
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.automation.application.events import DeliveryMessage, HandoffKind
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import EventRow
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.reconciliation import NotificationReconciler
from operations.modules.notifications.infrastructure.persistence import NoticeRow
from operations.modules.scheduling.application.contracts import (
    Assignment,
    Recurrence,
    ScheduleDefinition,
)
from operations.modules.tasks.application.service import TaskService
from operations.modules.tasks.infrastructure.persistence import ReminderRow
from operations.modules.workflows.infrastructure.runtime import NotificationRow
from operations.worker import process_notifications
from sqlalchemy import func, select
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import publish, setup
from test_phase5_api import activate, create_workflow, reviewer, submit
from test_phase6_actions import context
from test_phase6_periodic import task_fixture

pytestmark = pytest.mark.integration


def reconciler(api: Api) -> NotificationReconciler:
    services = compose(api.session)
    return NotificationReconciler(services.automation, services.tasks, services.workflow_runtime)


@contextmanager
def historical_capture(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    append = AuditedEventBus.append
    task_event = TaskService.event

    def old_append(self: AuditedEventBus, event: AuditEvent) -> None:
        previous = self.capture
        try:
            if event.type in {"task.reminder.created", "workflow.notification.requested"}:
                self.capture = None
            append(self, event)
        finally:
            self.capture = previous

    def old_task_event(self: TaskService, *args: object, **kwargs: object) -> None:
        if len(args) >= 3 and args[2] == "task.reminder.created":
            kwargs.update(event_id=uuid7(), reminder_id=None)
        task_event(self, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(AuditedEventBus, "append", old_append)
        patch.setattr(TaskService, "event", old_task_event)
        yield


def workflow_fixture(
    api: Api, monkeypatch: pytest.MonkeyPatch, *, historical: bool = True
) -> tuple[UUID, UUID, UUID]:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    recipient = reviewer(api, org, workspace)
    workflow = create_workflow(
        api,
        route,
        {
            "form_id": form,
            "form_number": 1,
            "nodes": [
                {"key": "start", "name": "Start", "kind": "start"},
                {
                    "key": "notify",
                    "name": "Notify",
                    "kind": "notify",
                    "assignments": [{"kind": "user", "target_id": str(recipient)}],
                },
                {"key": "end", "name": "End", "kind": "end"},
            ],
            "transitions": [
                {"source": "start", "target": "notify"},
                {"source": "notify", "target": "end"},
            ],
        },
    )
    activate(api, route, workflow)
    if historical:
        with historical_capture(monkeypatch):
            submit(api, route, form)
    else:
        submit(api, route, form)
    return org, workspace, recipient


def test_historical_reminder_preserves_old_audit_and_has_current_reconciliation_evidence(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    with historical_capture(monkeypatch):
        assert services.tasks.generate_reminders(actor, org, workspace, None, None)[0] == 1
    reminder = api.session.scalar(select(ReminderRow))
    old_audit = api.session.scalar(select(AuditRow).where(AuditRow.type == "task.reminder.created"))
    assert reminder and old_audit and old_audit.id != reminder.id
    original = (old_audit.id, old_audit.actor_id, old_audit.occurred_at, dict(old_audit.payload))
    count = api.session.scalar(select(func.count()).select_from(AuditRow))
    recovery = reconciler(api)
    preview = recovery.reconcile(actor, org, workspace, "task_reminder")
    assert len(preview.items) == 1 and preview.items[0].existing_event_id is None
    assert api.session.scalar(select(func.count()).select_from(AuditRow)) == count
    result = recovery.reconcile(
        actor,
        org,
        workspace,
        "task_reminder",
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Recover exact retained reminder",
    )
    assert result.created == 1 and result.applied
    event = services.automation.store.event(org, reminder.id)
    assert event and event.id == reminder.id and event.occurred_at > reminder.created_at
    assert (
        event.payload.reminder_id == reminder.id
        and event.payload.scheduled_at == reminder.scheduled_at
    )
    assert event.payload.recipient_ids == [UUID(item) for item in task.recipient_ids]
    assert event.payload.submission_id is None
    assert event.actor_id == services.authorization.user(actor, org).id
    assert services.automation.store.delivery(org, delivery_id(event.id, "automation")) is None
    assert services.automation.store.event_runs(org, event.id) == []
    message = DeliveryMessage(
        organization_id=org, delivery_id=delivery_id(event.id, "notifications")
    )
    assert process_notifications(api.session, message).state == "completed"
    notice = services.notifications.inbox(actor, org, workspace)[0][0].notice
    receipt = services.notifications.mark_read(actor, org, notice.id)
    with pytest.raises(ServiceError, match="notification_handoff_review_required"):
        recovery.reconcile(
            actor,
            org,
            workspace,
            "task_reminder",
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason="Repeated old preview",
        )
    reviewed = recovery.reconcile(actor, org, workspace, "task_reminder")
    assert reviewed.items[0].existing_event_id == event.id
    assert (
        recovery.reconcile(
            actor,
            org,
            workspace,
            "task_reminder",
            dry_run=False,
            review_sha256=reviewed.review_sha256,
            reason="Verify recovery",
        ).created
        == 0
    )
    assert services.notifications.mark_read(actor, org, notice.id) == receipt
    api.session.refresh(old_audit)
    assert (old_audit.id, old_audit.actor_id, old_audit.occurred_at, old_audit.payload) == original
    audit = api.session.scalar(
        select(AuditRow).where(AuditRow.type == "notification.handoff.reconciled")
    )
    assert (
        audit
        and datetime.fromisoformat(str(audit.payload["source_created_at"])) == reminder.created_at
    )


def test_historical_notify_uses_exact_intent_and_minimal_recipient_access(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, recipient_id = workflow_fixture(api, monkeypatch)
    actor, _ = context(api, org)
    services = compose(api.session)
    intent = api.session.scalar(select(NotificationRow))
    assert intent
    snapshot = list(intent.recipient_ids)
    preview = reconciler(api).reconcile(actor, org, workspace, "workflow_notify")
    assert preview.items[0].existing_event_id is None
    reconciler(api).reconcile(
        actor,
        org,
        workspace,
        "workflow_notify",
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Recover notify visit",
    )
    message = DeliveryMessage(
        organization_id=org, delivery_id=delivery_id(intent.id, "notifications")
    )
    assert process_notifications(api.session, message).state == "completed"
    recipient = services.identity.active_context(org, recipient_id, actor)
    items, _ = services.notifications.inbox(recipient, org, workspace)
    assert len(items) == 1 and items[0].notice.source_intent_id == intent.id
    with pytest.raises(ServiceError):
        services.workflow_runtime.access(recipient, org, workspace, intent.instance_id)
    assert list(intent.recipient_ids) == snapshot


@pytest.mark.parametrize("kind", ["task_reminder", "workflow_notify"])
def test_existing_handoffs_are_reported_without_new_events_or_requeue(
    api: Api, monkeypatch: pytest.MonkeyPatch, kind: HandoffKind
) -> None:
    if kind == "task_reminder":
        actor, org, workspace, _ = task_fixture(api)
        compose(api.session).tasks.generate_reminders(actor, org, workspace, None, None)
    else:
        org, workspace, _ = workflow_fixture(api, monkeypatch, historical=False)
        actor, _ = context(api, org)
    recovery = reconciler(api)
    preview = recovery.reconcile(actor, org, workspace, kind)
    assert len(preview.items) == 1 and preview.items[0].existing_event_id
    before = api.session.scalar(select(func.count()).select_from(EventRow))
    result = recovery.reconcile(
        actor,
        org,
        workspace,
        kind,
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Verify handoff",
    )
    assert (
        result.created == 0
        and api.session.scalar(select(func.count()).select_from(EventRow)) == before
    )


@pytest.mark.parametrize("reason", [None, "  ", "x" * 501])
def test_review_and_reason_required_without_side_effects(
    api: Api, monkeypatch: pytest.MonkeyPatch, reason: str | None
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    with historical_capture(monkeypatch):
        compose(api.session).tasks.generate_reminders(actor, org, workspace, None, None)
    recovery = reconciler(api)
    preview = recovery.reconcile(actor, org, workspace, "task_reminder")
    with pytest.raises(ServiceError, match="notification_handoff_review_required"):
        recovery.reconcile(actor, org, workspace, "task_reminder", dry_run=False)
    with pytest.raises(ServiceError, match="notification_handoff_reason_required"):
        recovery.reconcile(
            actor,
            org,
            workspace,
            "task_reminder",
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason=reason,
        )
    assert recovery.reconcile(actor, org, workspace, "task_reminder") == preview


def test_reconcile_does_not_delegate_operator_privileges_to_revoked_recipient(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, recipient = workflow_fixture(api, monkeypatch)
    actor, _ = context(api, org)
    services = compose(api.session)
    preview = reconciler(api).reconcile(actor, org, workspace, "workflow_notify")
    grant = api.session.scalar(select(GrantRow).where(GrantRow.user_id == recipient))
    assert grant
    services.authorization.revoke(actor, org, grant.id)
    result = reconciler(api).reconcile(
        actor,
        org,
        workspace,
        "workflow_notify",
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Recover original intent",
    )
    assert result.created == 1
    message = DeliveryMessage(
        organization_id=org, delivery_id=delivery_id(result.items[0].intent_id, "notifications")
    )
    assert process_notifications(api.session, message).state == "completed"
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    with pytest.raises(ServiceError):
        reconciler(api).reconcile(actor, uuid7(), workspace, "workflow_notify")
    with pytest.raises(ServiceError):
        reconciler(api).reconcile(actor, org, uuid7(), "workflow_notify")


def test_apply_rechecks_operator_authority_and_existing_source_integrity(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    services = compose(api.session)
    with historical_capture(monkeypatch):
        services.tasks.generate_reminders(actor, org, workspace, None, None)
    recovery = reconciler(api)
    preview = recovery.reconcile(actor, org, workspace, "task_reminder")
    token = services.identity.invite(
        actor,
        "replacement@example.test",
        Role.ORGANIZATION_ADMIN,
        Scope(org, ScopeType.ORGANIZATION, org),
    )
    replacement = RequestContext(
        Principal(actor.principal.issuer, "replacement", "replacement@example.test", True),
        uuid7(),
        uuid7(),
    )
    services.identity.accept(replacement, org, token)
    grant = api.session.scalar(
        select(GrantRow).where(
            GrantRow.organization_id == org,
            GrantRow.user_id == services.authorization.user(actor, org).id,
        )
    )
    assert grant
    services.authorization.revoke(replacement, org, grant.id)
    with pytest.raises(ServiceError):
        recovery.reconcile(
            actor,
            org,
            workspace,
            "task_reminder",
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason="Stale operator access",
        )
    assert services.automation.store.event(org, preview.items[0].intent_id) is None
    fresh = recovery.reconcile(replacement, org, workspace, "task_reminder")
    recovery.reconcile(
        replacement,
        org,
        workspace,
        "task_reminder",
        dry_run=False,
        review_sha256=fresh.review_sha256,
        reason="Fresh authorized operator",
    )
    source = services.tasks.notification_handoffs(replacement, org, workspace, None)[0]
    with pytest.raises(ServiceError, match="notification_handoff_source_integrity"):
        services.automation.notification_handoff_event(
            source.model_copy(update={"source_id": uuid7()})
        )


def test_index_only_populated_rollback_preserves_reconciled_evidence(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    with historical_capture(monkeypatch):
        compose(api.session).tasks.generate_reminders(actor, org, workspace, None, None)
    preview = reconciler(api).reconcile(actor, org, workspace, "task_reminder")
    result = reconciler(api).reconcile(
        actor,
        org,
        workspace,
        "task_reminder",
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Migration fixture",
    )
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("34e34c3ce85a")
    assert revision
    with (
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()
        assert compose(api.session).automation.store.event(org, result.items[0].intent_id)
        revision.module.upgrade()


def test_historical_pages_and_atomic_capture_failure(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    start = datetime.now(UTC) - timedelta(hours=105)
    schedule = services.scheduling.create(
        actor,
        org,
        workspace,
        None,
        "Paged reminders",
        ScheduleDefinition(
            form_id=task.form_id,
            form_number=task.form_number,
            recurrence=Recurrence(kind="interval", at=start, interval_seconds=3600),
            assignments=[
                Assignment(kind="user", target_id=services.authorization.user(actor, org).id)
            ],
            due_after_seconds=0,
            reminder_offsets=[0],
        ),
    )
    reviewed = services.scheduling.activate(actor, org, workspace, schedule.id, 1, 1, True, None)
    services.scheduling.activate(
        actor, org, workspace, schedule.id, 1, 1, False, reviewed.content_sha256
    )
    services.tasks.materialize(
        actor, org, workspace, schedule.id, start, start + timedelta(hours=102, seconds=1), False
    )
    with historical_capture(monkeypatch):
        _, cursor = services.tasks.generate_reminders(actor, org, workspace, None, None)
        assert cursor
        services.tasks.generate_reminders(actor, org, workspace, None, cursor)
    recovery = reconciler(api)
    preview = recovery.reconcile(actor, org, workspace, "task_reminder")
    assert len(preview.items) == 100 and preview.cursor
    from operations.modules.automation.application.service import AutomationService

    capture = AutomationService.capture_notification_handoff
    calls = 0

    def fail_after_first(self: AutomationService, *args: object, **kwargs: object) -> UUID:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ServiceError(503, "test_dependency_unavailable")
        return capture(self, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(AutomationService, "capture_notification_handoff", fail_after_first)
        with pytest.raises(ServiceError), api.session.begin_nested():
            recovery.reconcile(
                actor,
                org,
                workspace,
                "task_reminder",
                dry_run=False,
                review_sha256=preview.review_sha256,
                reason="Atomic recovery",
            )
    assert recovery.reconcile(actor, org, workspace, "task_reminder") == preview
    assert (
        recovery.reconcile(
            actor,
            org,
            workspace,
            "task_reminder",
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason="Recover page",
        ).created
        == 100
    )
    second = recovery.reconcile(actor, org, workspace, "task_reminder", preview.cursor)
    assert len(second.items) == 4 and second.cursor is None
