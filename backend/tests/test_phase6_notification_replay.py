from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.events import DeliveryMessage
from operations.modules.iam.application.contracts import Role, Scope, ScopeType
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.consumer import NotificationConsumer
from operations.modules.notifications.infrastructure.persistence import AttemptRow, NoticeRow
from operations.worker import process_notifications
from sqlalchemy import func, select
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase6_automatic_notices import dispatch
from test_phase6_periodic import task_fixture

pytestmark = pytest.mark.integration


def fail_delivery(api: Api, message: DeliveryMessage, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object) -> tuple[int, int]:
        raise ServiceError(422, "test_notification_failure")

    with monkeypatch.context() as patch:
        patch.setattr(NotificationConsumer, "deliver", fail)
        result = process_notifications(api.session, message)
    assert result.state == "dead_letter" and result.attempts == 1


def test_review_requeue_preserves_source_attempts_and_read_history(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")
    fail_delivery(api, message, monkeypatch)
    service = compose(api.session).automation
    source_before = service.store.event(org, service.notification_delivery(message)[0].event_id)
    assert source_before is not None
    audit_count = api.session.scalar(select(func.count()).select_from(AuditRow))
    preview = service.replay_notification(actor, org, workspace, message.delivery_id)
    assert not preview.applied and preview.delivery.state == "dead_letter"
    assert api.session.scalar(select(func.count()).select_from(AuditRow)) == audit_count
    result = service.replay_notification(
        actor,
        org,
        workspace,
        message.delivery_id,
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason=" Retry after adapter repair ",
    )
    assert result.applied and result.delivery.state == "retry" and result.delivery.attempts == 1
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == 1
    with pytest.raises(ServiceError, match="notification_replay_review_required"):
        service.replay_notification(
            actor,
            org,
            workspace,
            message.delivery_id,
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason="Duplicate request",
        )
    completed = process_notifications(api.session, message)
    assert completed.state == "completed" and completed.attempts == 2
    assert service.store.event(org, completed.event_id) == source_before
    notices = compose(api.session).notifications
    items, _ = notices.inbox(actor, org, workspace)
    assert len(items) == 1
    receipt = notices.mark_read(actor, org, items[0].notice.id)
    assert process_notifications(api.session, message) == completed
    assert notices.mark_read(actor, org, items[0].notice.id) == receipt
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == 2
    audit = api.session.scalar(
        select(AuditRow).where(AuditRow.type == "outbox.notification.replayed")
    )
    assert (
        audit
        and audit.actor_id is not None
        and audit.correlation_id == source_before.correlation_id
    )
    assert audit.payload["reason"] == "Retry after adapter repair"
    assert audit.payload["version"] == 1 and audit.payload["outcome"] == "dead_letter"
    with pytest.raises(ServiceError, match="notification_delivery_not_replayable"):
        service.replay_notification(actor, org, workspace, message.delivery_id)


@pytest.mark.parametrize("reason", [None, "   ", "x" * 501])
def test_apply_requires_review_and_bounded_reason(
    api: Api, monkeypatch: pytest.MonkeyPatch, reason: str | None
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")
    fail_delivery(api, message, monkeypatch)
    service = compose(api.session).automation
    preview = service.replay_notification(actor, org, workspace, message.delivery_id)
    with pytest.raises(ServiceError, match="notification_replay_review_required"):
        service.replay_notification(actor, org, workspace, message.delivery_id, dry_run=False)
    with pytest.raises(ServiceError, match="notification_replay_reason_required"):
        service.replay_notification(
            actor,
            org,
            workspace,
            message.delivery_id,
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason=reason,
        )
    assert service.notification_delivery(message)[0] == preview.delivery
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(AuditRow.type == "outbox.notification.replayed")
        )
        == 0
    )


def test_scope_consumer_and_live_operator_authority(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")
    fail_delivery(api, message, monkeypatch)
    service = compose(api.session).automation
    preview = service.replay_notification(actor, org, workspace, message.delivery_id)
    for target_org, target_workspace, identifier in (
        (uuid7(), workspace, message.delivery_id),
        (org, uuid7(), message.delivery_id),
        (org, workspace, uuid7()),
    ):
        with pytest.raises(ServiceError):
            service.replay_notification(actor, target_org, target_workspace, identifier)
    from operations.modules.automation.domain.reliability import delivery_id

    with pytest.raises(ServiceError, match="notification_delivery_not_found"):
        service.replay_notification(
            actor, org, workspace, delivery_id(preview.delivery.event_id, "automation")
        )
    grant = api.session.scalar(select(GrantRow).where(GrantRow.organization_id == org))
    assert grant
    services = compose(api.session)
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
    services.authorization.revoke(replacement, org, grant.id)
    with pytest.raises(ServiceError):
        service.replay_notification(
            actor,
            org,
            workspace,
            message.delivery_id,
            dry_run=False,
            review_sha256=preview.review_sha256,
            reason="Stale authority",
        )
    assert service.notification_delivery(message)[0] == preview.delivery


def test_worker_rechecks_recipient_after_replay_and_does_not_backfill_completed_skips(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, task = task_fixture(api)
    message = dispatch(api, org, "task.created")
    fail_delivery(api, message, monkeypatch)
    services = compose(api.session)
    preview = services.automation.replay_notification(actor, org, workspace, message.delivery_id)
    services.automation.replay_notification(
        actor,
        org,
        workspace,
        message.delivery_id,
        dry_run=False,
        review_sha256=preview.review_sha256,
        reason="Repair complete",
    )
    services.tasks.cancel(actor, org, workspace, task.id, 1, "Cancelled before retry", False)
    completed = process_notifications(api.session, message)
    assert completed.state == "completed"
    attempts = api.session.scalars(select(AttemptRow).order_by(AttemptRow.number)).all()
    assert len(attempts) == 2 and attempts[1].created == 0 and attempts[1].skipped == 1
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 0
    with pytest.raises(ServiceError, match="notification_delivery_not_replayable"):
        services.automation.replay_notification(actor, org, workspace, message.delivery_id)


def test_retry_preview_conflicts_with_worker_progress_and_total_limit(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, _ = task_fixture(api)
    message = dispatch(api, org, "task.created")
    service = compose(api.session).automation

    def fail(*args: object) -> tuple[int, int]:
        raise ServiceError(503, "test_transient")

    with monkeypatch.context() as patch:
        patch.setattr(NotificationConsumer, "deliver", fail)
        result = process_notifications(api.session, message)
        preview = service.replay_notification(actor, org, workspace, message.delivery_id)
        service.complete_notification_delivery(
            result.model_copy(update={"next_at": datetime.now(UTC) - timedelta(seconds=1)})
        )
        result = process_notifications(api.session, message)
        with pytest.raises(ServiceError, match="notification_replay_review_required"):
            service.replay_notification(
                actor,
                org,
                workspace,
                message.delivery_id,
                dry_run=False,
                review_sha256=preview.review_sha256,
                reason="Stale preview",
            )
        for number in range(3, 21):
            preview = service.replay_notification(actor, org, workspace, message.delivery_id)
            service.replay_notification(
                actor,
                org,
                workspace,
                message.delivery_id,
                dry_run=False,
                review_sha256=preview.review_sha256,
                reason="Reviewed repair attempt",
            )
            result = process_notifications(api.session, message)
            assert result.attempts == number
        assert result.state == "dead_letter"
    with pytest.raises(ServiceError, match="notification_attempt_limit"):
        service.replay_notification(actor, org, workspace, message.delivery_id)
    assert api.session.scalar(select(func.count()).select_from(AttemptRow)) == 20
