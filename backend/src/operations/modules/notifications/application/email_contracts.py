from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field

from operations.contracts import Command

type EmailState = Literal["pending", "sending", "sent", "retry", "uncertain", "failed", "skipped"]
type EmailKind = Literal["invitation", "notice"]


class EmailDelivery(Command):
    id: UUID
    organization_id: UUID
    source_kind: EmailKind
    source_id: UUID
    recipient_id: UUID | None
    operator_id: UUID
    correlation_id: UUID
    request_id: UUID
    created_at: AwareDatetime
    state: EmailState = "pending"
    attempts: int = Field(default=0, ge=0, le=20)
    next_at: AwareDatetime
    error_code: str | None = None


class EmailAttempt(Command):
    id: UUID
    organization_id: UUID
    delivery_id: UUID
    number: int = Field(ge=1, le=20)
    outcome: EmailState
    error_code: str | None
    occurred_at: AwareDatetime


@dataclass(frozen=True)
class EmailContent:
    recipient: str
    subject: str
    text: str


@dataclass(frozen=True)
class EmailResult:
    state: Literal["sent", "retry", "failed", "uncertain"]
    code: str | None = None


class EmailTransport(Protocol):
    def send(self, identifier: UUID, content: EmailContent) -> EmailResult: ...


class EmailStore(Protocol):
    def get(self, org: UUID, identifier: UUID) -> EmailDelivery | None: ...
    def add(self, delivery: EmailDelivery) -> None: ...
    def save(self, delivery: EmailDelivery) -> None: ...
    def attempt(self, attempt: EmailAttempt) -> None: ...
    def due(self, org: UUID, now: datetime) -> list[UUID]: ...


class EmailReview(Command):
    delivery: EmailDelivery
    review_sha256: str
    applied: bool = False


class EmailDispatch(Command):
    organization_id: UUID
    due: int = Field(ge=0, le=100)
    dispatched: int = Field(ge=0, le=100)
