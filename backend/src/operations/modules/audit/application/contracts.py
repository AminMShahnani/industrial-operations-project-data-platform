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
