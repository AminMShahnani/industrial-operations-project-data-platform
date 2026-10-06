from collections.abc import Callable, Generator
from contextlib import contextmanager
from uuid import UUID

from operations.modules.audit.application.contracts import AuditEvent, AuditWriter
from operations.modules.automation.application.contracts import Run
from operations.modules.automation.application.events import (
    EventContext,
    EventType,
    OperationalEvent,
)


class AuditedEventBus:
    def __init__(self, audit: AuditWriter) -> None:
        self.audit = audit
        self.capture: Callable[[OperationalEvent], None] | None = None
        self.origin: tuple[UUID, OperationalEvent, Run] | None = None

    @contextmanager
    def delegated(self, version: UUID, event: OperationalEvent, run: Run) -> Generator[None]:
        previous = self.origin
        self.origin = (version, event, run)
        try:
            yield
        finally:
            self.origin = previous

    def append(self, event: AuditEvent) -> None:
        payload = event.payload
        if self.origin:
            version, source, run = self.origin
            payload = payload.model_copy(
                update={
                    "run_id": run.id,
                    "rule_version_id": version,
                    "trigger_actor_id": source.actor_id,
                    "authorization_kind": "delegated_automation",
                    "authorized_by": run.delegator_id,
                }
            )
            event = event.model_copy(update={"payload": payload})
        self.audit.append(event)
        if self.capture is None or event.organization_id is None or event.aggregate_id is None:
            return
        mapping: dict[str, EventType] = {
            "submission.draft.created": "submission.created",
            "submission.revision.draft.created": "submission.created",
            "submission.submitted": "submission.submitted",
            "workflow.step.assigned": "workflow.step.entered",
            "workflow.step.completed": "workflow.step.completed",
            "task.created": "task.created",
            "task.due": "task.due",
            "task.overdue": "task.overdue",
            "project.transitioned": "project.phase.changed",
            "master_data.record.created": "master_data.changed",
            "master_data.record.updated": "master_data.changed",
            "timer.fired": "scheduled.timer",
        }
        kind = mapping.get(event.type)
        if event.type == "workflow.instance.approved":
            kind = "submission.approved"
        if event.type == "workflow.instance.rejected":
            kind = "submission.rejected"
        if kind is None:
            return
        aggregate: dict[str, str] = {
            "submission": "submission",
            "workflow": "workflow",
            "task": "task",
            "project": "project",
            "master_data": "master_data",
            "timer": "timer",
        }
        category = aggregate.get(event.aggregate_type)
        if category is None:
            return
        context = EventContext.model_validate(
            {key: getattr(payload, key) for key in EventContext.model_fields}
        )
        data = OperationalEvent.model_validate(
            dict(
                id=event.id,
                type=kind,
                occurred_at=event.occurred_at,
                organization_id=event.organization_id,
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                actor_id=event.actor_id,
                correlation_id=event.correlation_id,
                aggregate_type=category,
                aggregate_id=event.aggregate_id,
                payload=context,
            )
        )
        if self.origin:
            version, source, _ = self.origin
            data = data.model_copy(
                update={
                    "causation_id": source.id,
                    "causation_path": [*source.causation_path, version],
                }
            )
        self.capture(data)
