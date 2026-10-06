from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from uuid import uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.events import Delivery, DeliveryMessage
from operations.modules.automation.application.service import AutomationService


class AutomationConsumer:
    def __init__(
        self, service: AutomationService, savepoint: Callable[[], AbstractContextManager[None]]
    ) -> None:
        self.service, self.savepoint = service, savepoint

    def consume(self, message: DeliveryMessage) -> Delivery:
        org = message.organization_id
        store = self.service.store
        delivery = store.delivery(org, message.delivery_id, True)
        if delivery is None:
            raise ServiceError(404, "outbox_delivery_not_found")
        if delivery.consumer != "automation":
            raise ServiceError(422, "outbox_consumer_not_configured")
        if delivery.state in {"completed", "dead_letter"}:
            return delivery
        if delivery.next_at > datetime.now(UTC) and delivery.state != "dispatched":
            return delivery
        source = store.event(org, delivery.event_id)
        if source is None:
            raise ServiceError(409, "outbox_delivery_integrity")
        runs = store.event_runs(org, source.id)
        for run in runs:
            if run.state in {"completed", "skipped", "dead_letter"} or run.next_at > datetime.now(
                UTC
            ):
                continue
            try:
                # Every action/receipt/audit/caused event rolls back together on failure.
                with self.savepoint():
                    self.service.execute(org, run.id)
            except ServiceError as error:
                self.service.failed(org, run.id, error.code, error.status == 503)
        current = store.event_runs(org, source.id)
        waiting = [run for run in current if run.state in {"pending", "retry"}]
        now = datetime.now(UTC)
        state = (
            "retry"
            if waiting
            else "dead_letter"
            if any(run.state == "dead_letter" for run in current)
            else "completed"
        )
        changed = Delivery.model_validate(
            {
                **delivery.model_dump(),
                "state": state,
                "next_at": min(run.next_at for run in waiting) if waiting else now,
                "error_code": "automation_runs_failed" if state == "dead_letter" else None,
            }
        )
        store.save_delivery(changed)
        self.service.audit.append(
            AuditEvent(
                id=uuid7(),
                type="outbox.delivery." + state,
                occurred_at=now,
                organization_id=org,
                actor_id=None,
                correlation_id=source.correlation_id,
                request_id=delivery.id,
                aggregate_type="outbox_delivery",
                aggregate_id=delivery.id,
                payload=AuditDetails(
                    workspace_id=source.workspace_id,
                    project_id=source.project_id,
                    reason="durable_automation_consumer",
                ),
            )
        )
        return changed
