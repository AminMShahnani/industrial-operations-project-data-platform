from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import Field

from operations.contracts import Command


class AuditDetails(Command):
    reason: str | None = None
    target_id: UUID | None = None
    authorized_by: UUID | None = None
    role: str | None = None
    scope_type: str | None = None
    scope_id: UUID | None = None
    version: int | None = None
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    form_id: UUID | None = None
    form_number: int | None = None
    submission_id: UUID | None = None
    workflow_instance_id: UUID | None = None
    task_id: UUID | None = None
    master_data_type_id: UUID | None = None
    master_data_record_id: UUID | None = None
    recipient_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    subject_user_id: UUID | None = None
    phase: str | None = None
    outcome: str | None = None
    run_id: UUID | None = None
    rule_version_id: UUID | None = None
    trigger_actor_id: UUID | None = None
    authorization_kind: str | None = None


class AuditEvent(Command):
    id: UUID
    type: str
    occurred_at: datetime
    organization_id: UUID | None
    actor_id: UUID | None
    actor_issuer: str | None = None
    actor_subject: str | None = None
    correlation_id: UUID
    request_id: UUID
    aggregate_type: str
    aggregate_id: UUID | None
    payload_version: int = 1
    payload: AuditDetails = Field(default_factory=AuditDetails)


class AuditWriter(Protocol):
    def append(self, event: AuditEvent) -> None: ...
