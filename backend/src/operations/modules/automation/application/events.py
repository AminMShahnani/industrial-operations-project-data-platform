"""Typed asynchronous event intent; broker messages contain scoped IDs only."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command

type EventType = Literal[
    "submission.created",
    "submission.submitted",
    "submission.approved",
    "submission.rejected",
    "workflow.step.entered",
    "workflow.step.completed",
    "task.created",
    "task.due",
    "task.overdue",
    "project.phase.changed",
    "master_data.changed",
    "scheduled.timer",
    "integration.event",
]


class EventContext(Command):
    subject_user_id: UUID | None = None
    form_id: UUID | None = None
    form_number: int | None = Field(default=None, ge=1)
    submission_id: UUID | None = None
    workflow_instance_id: UUID | None = None
    task_id: UUID | None = None
    master_data_type_id: UUID | None = None
    master_data_record_id: UUID | None = None
    phase: str | None = Field(default=None, min_length=1, max_length=60)
    recipient_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def coherent(self) -> EventContext:
        if (self.form_id is None) != (self.form_number is None):
            raise ValueError("event_form_pin_required")
        return self


class OperationalEvent(Command):
    id: UUID
    type: EventType
    occurred_at: datetime
    organization_id: UUID
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    actor_id: UUID | None = None
    correlation_id: UUID
    causation_id: UUID | None = None
    causation_path: list[UUID] = Field(default_factory=list, max_length=16)
    aggregate_type: Literal[
        "submission", "workflow", "task", "project", "master_data", "timer", "integration"
    ]
    aggregate_id: UUID
    payload_version: Literal[1] = 1
    payload: EventContext = Field(default_factory=EventContext)

    @model_validator(mode="after")
    def bounded(self) -> OperationalEvent:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("event_timestamp_requires_timezone")
        if len(set(self.causation_path)) != len(self.causation_path):
            raise ValueError("duplicate_event_causation")
        if self.project_id is not None and self.workspace_id is None:
            raise ValueError("event_project_requires_workspace")
        return self


class DeliveryMessage(Command):
    organization_id: UUID
    delivery_id: UUID


class Delivery(Command):
    id: UUID
    organization_id: UUID
    event_id: UUID
    consumer: Literal["automation", "notifications"]
    state: Literal["pending", "dispatched", "completed", "retry", "dead_letter"] = "pending"
    attempts: int = Field(default=0, ge=0, le=20)
    next_at: datetime
    error_code: str | None = None


class EventWriter(Protocol):
    def append(self, event: OperationalEvent) -> None: ...


class JobPublisher(Protocol):
    def publish(self, message: DeliveryMessage) -> None: ...
