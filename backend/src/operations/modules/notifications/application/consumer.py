from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, uuid5, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.events import (
    Delivery,
    DeliveryMessage,
    OperationalEvent,
    delivery_retry_delay,
)
from operations.modules.automation.application.service import AutomationService
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.notifications.application.contracts import (
    Notice,
    NoticeTopic,
    NotificationAttempt,
)
from operations.modules.notifications.application.service import NotificationService


class NotificationConsumer:
    def __init__(
        self,
        notifications: NotificationService,
        deliveries: AutomationService,
        savepoint: Callable[[], AbstractContextManager[None]],
    ) -> None:
        self.notifications, self.deliveries, self.savepoint = notifications, deliveries, savepoint

    def deliver(self, delivery: Delivery, source: OperationalEvent) -> tuple[int, int]:
        topics: dict[str, NoticeTopic] = {
            "task.created": "work_assigned",
            "task.due": "rule_notice",
            "task.overdue": "rule_notice",
            "task.reminder.created": "rule_notice",
            "workflow.step.entered": "review_requested",
            "workflow.notification.requested": "rule_notice",
        }
        topic = topics.get(source.type)
        if topic is None:
            return 0, 0
        if source.workspace_id is None:
            raise ServiceError(409, "notification_source_scope_mismatch")
        workflow = source.type.startswith("workflow.")
        kind: Literal["workflow", "task"] = "workflow" if workflow else "task"
        identifier = source.payload.workflow_instance_id if workflow else source.payload.task_id
        intent = source.aggregate_id if workflow else source.id
        if identifier is None or len(set(source.payload.recipient_ids)) != len(
            source.payload.recipient_ids
        ):
            raise ServiceError(409, "notification_source_integrity")
        context = RequestContext(
            Principal("internal", "notification-worker"), delivery.id, source.correlation_id
        )
        created = skipped = 0
        for recipient_id in source.payload.recipient_ids:
            notice = Notice(
                id=uuid5(NAMESPACE_URL, f"operations:automatic-notice:{source.id}:{recipient_id}"),
                organization_id=source.organization_id,
                workspace_id=source.workspace_id,
                project_id=source.project_id,
                recipient_id=recipient_id,
                event_id=source.id,
                origin="automatic",
                source_intent_id=intent,
                topic=topic,
                source_kind=kind,
                source_id=identifier,
                created_at=datetime.now(UTC),
            )
            try:
                recipient = self.notifications.identity.active_context(
                    source.organization_id, recipient_id, context
                )
                self.notifications.sources.require(
                    recipient,
                    source.organization_id,
                    source.workspace_id,
                    source.project_id,
                    kind,
                    identifier,
                    intent if workflow else None,
                )
                if not workflow:
                    self.notifications.sources.tasks.notification_delivery_access(
                        recipient, source.organization_id, source.workspace_id, identifier
                    )
            except ServiceError as error:
                if error.status not in {403, 404}:
                    raise
                skipped += 1
                self.audit(source, delivery, "notification.recipient.skipped", notice, error.code)
                continue
            if (
                self.notifications.store.get(source.organization_id, recipient_id, notice.id)
                is None
            ):
                self.audit(
                    source, delivery, "notification.created", notice, "automatic_source_notice"
                )
                self.notifications.store.add(notice)
                created += 1
        return created, skipped

    def audit(
        self,
        source: OperationalEvent,
        delivery: Delivery,
        action: str,
        notice: Notice | None = None,
        reason: str | None = None,
    ) -> None:
        self.notifications.identity.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=source.organization_id,
                actor_id=None,
                correlation_id=source.correlation_id,
                request_id=delivery.id,
                aggregate_type="notification" if notice else "outbox_delivery",
                aggregate_id=notice.id if notice else delivery.id,
                payload=AuditDetails(
                    workspace_id=source.workspace_id,
                    project_id=source.project_id,
                    target_id=notice.recipient_id if notice else None,
                    reason=reason,
                ),
            )
        )

    def consume(self, message: DeliveryMessage) -> Delivery:
        delivery, source = self.deliveries.notification_delivery(message)
        now = datetime.now(UTC)
        if delivery.state in {"completed", "dead_letter"} or (
            delivery.next_at > now and delivery.state != "dispatched"
        ):
            return delivery
        if delivery.attempts >= 20:
            raise ServiceError(409, "notification_attempt_limit")
        created = skipped = 0
        outcome: Literal["completed", "retry", "dead_letter"] = "completed"
        code: str | None = None
        delay: int | None = None
        number = delivery.attempts + 1
        try:
            with self.savepoint():
                created, skipped = self.deliver(delivery, source)
        except ServiceError as error:
            code = error.code
            delay = delivery_retry_delay(number) if error.status == 503 and number <= 8 else None
            outcome = "retry" if delay is not None else "dead_letter"
        changed = delivery.model_copy(
            update={
                "state": outcome,
                "attempts": number,
                "next_at": datetime.now(UTC) + timedelta(seconds=delay or 0),
                "error_code": code,
            }
        )
        self.deliveries.complete_notification_delivery(changed)
        self.audit(
            source, changed, "outbox.notification." + outcome, reason=code or "fixed_source_notice"
        )
        self.notifications.store.add_attempt(
            NotificationAttempt(
                id=uuid7(),
                organization_id=source.organization_id,
                delivery_id=delivery.id,
                number=number,
                outcome=outcome,
                created=created,
                skipped=skipped,
                error_code=code,
                occurred_at=datetime.now(UTC),
            )
        )
        return changed
