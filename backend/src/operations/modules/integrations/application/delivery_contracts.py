"""Immutable, identifiers-only webhook action intents."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command


class WebhookIntent(Command):
    id: UUID
    audit_id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    event_id: UUID
    run_id: UUID
    rule_version_id: UUID
    action_position: int = Field(ge=0, le=19)
    endpoint_id: UUID
    endpoint_version: int = Field(ge=1)
    requested_by_id: UUID
    correlation_id: UUID
    created_at: datetime

    @model_validator(mode="after")
    def coherent(self) -> WebhookIntent:
        if self.created_at.utcoffset() is None:
            raise ValueError("webhook_intent_timestamp_requires_timezone")
        return self


class WebhookIntentStore(Protocol):
    def get(self, organization_id: UUID, identifier: UUID) -> WebhookIntent | None: ...
    def add(self, row: WebhookIntent) -> None: ...
