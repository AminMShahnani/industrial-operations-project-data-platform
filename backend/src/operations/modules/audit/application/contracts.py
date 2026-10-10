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
    signing_key_version: int | None = Field(default=None, ge=1)
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
    storage_etag: str | None = Field(default=None, max_length=128)
    storage_modified_at: datetime | None = None
    storage_grace_seconds: int | None = Field(default=None, ge=86400, le=2592000)
    scheduled_at: datetime | None = None
    timer_version_id: UUID | None = None
    reminder_id: UUID | None = None
    source_created_at: datetime | None = None


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


class AuditReader(Protocol):
    def get(self, org: UUID, identifier: UUID) -> AuditEvent | None: ...
