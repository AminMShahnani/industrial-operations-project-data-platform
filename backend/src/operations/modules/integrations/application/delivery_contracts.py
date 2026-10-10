"""Immutable, identifiers-only webhook action intents."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.automation.application.contracts import RuleVersion, Run
from operations.modules.automation.application.events import OperationalEvent

WebhookDeliveryStatus = Literal[
    "pending", "sending", "retry", "sent", "failed", "uncertain", "skipped"
]
WebhookAttemptOutcome = Literal["sent", "retry", "failed", "uncertain", "skipped"]


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


class WebhookDeliveryState(Command):
    id: UUID
    organization_id: UUID
    status: WebhookDeliveryStatus
    attempts: int = Field(ge=0, le=20)
    next_at: datetime
    error_code: str | None = None
    updated_at: datetime
    audit_id: UUID


class WebhookAttempt(Command):
    id: UUID
    organization_id: UUID
    delivery_id: UUID
    number: int = Field(ge=1, le=20)
    outcome: WebhookAttemptOutcome
    error_code: str | None = None
    started_at: datetime
    finished_at: datetime
    audit_id: UUID


class WebhookDeliveryStore(Protocol):
    def intent(self, organization_id: UUID, identifier: UUID) -> WebhookIntent | None: ...
    def state(
        self, organization_id: UUID, identifier: UUID, lock: bool = False
    ) -> WebhookDeliveryState | None: ...
    def save_state(self, row: WebhookDeliveryState) -> None: ...
    def add_attempt(self, row: WebhookAttempt) -> None: ...


class WebhookDeliveryAdminStore(WebhookDeliveryStore, Protocol):
    def attempts(self, organization_id: UUID, identifier: UUID) -> list[WebhookAttempt]: ...

    def page(
        self,
        organization_id: UUID,
        workspace_id: UUID | None,
        project_id: UUID | None,
        state: WebhookDeliveryStatus | None,
        cursor: UUID | None,
        limit: int = 101,
    ) -> list[tuple[WebhookIntent, WebhookDeliveryState]]: ...


class WebhookSourceReader(Protocol):
    def event(self, organization_id: UUID, identifier: UUID) -> OperationalEvent | None: ...


class WebhookDeliveryAuthorityReader(WebhookSourceReader, Protocol):
    def run(self, organization_id: UUID, identifier: UUID, lock: bool = False) -> Run | None: ...

    def version_by_id(self, organization_id: UUID, identifier: UUID) -> RuleVersion | None: ...


class WebhookDeliveryPage(Command):
    items: list[WebhookDeliveryView]
    next_cursor: UUID | None = None


class WebhookDeliveryView(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    endpoint_id: UUID
    endpoint_version: int
    state: WebhookDeliveryStatus
    attempts: int
    next_at: datetime
    error_code: str | None
    created_at: datetime


class WebhookAttemptView(Command):
    number: int
    outcome: WebhookAttemptOutcome
    error_code: str | None
    started_at: datetime
    finished_at: datetime


class WebhookDeliveryHistory(Command):
    delivery: WebhookDeliveryView
    attempts: list[WebhookAttemptView]


class WebhookDeliveryReview(Command):
    delivery: WebhookDeliveryView
    review_sha256: str
    applied: bool = False
