from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.forms.application.contracts import FormValues, RuntimeResult


class SignatureEvidence(Command):
    key: str
    signer_id: UUID
    occurred_at: datetime
    reason: str


class Submission(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    form_id: UUID
    form_version_id: UUID
    form_number: int
    owner_id: UUID
    state: Literal["draft", "submitted"] = "draft"
    values: FormValues
    revision: int = 1
    submitted_at: datetime | None = None
    submit_key: UUID | None = None
    content_sha256: str | None = None
    signatures: list[SignatureEvidence] = Field(default_factory=list)


class SubmissionAggregateQuery(Command):
    """A form-scoped, bounded aggregate query; never returns submission identity."""

    form_id: UUID
    form_number: int = Field(ge=1)
    time_field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    start_date: date
    end_date: date
    metric: Literal["count", "sum", "average"]
    source_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")
    group_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")

    @model_validator(mode="after")
    def coherent(self) -> SubmissionAggregateQuery:
        if self.end_date < self.start_date:
            raise ValueError("aggregate_window_invalid")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("aggregate_window_exceeds_366_days")
        if self.metric in {"sum", "average"} and self.source_field is None:
            raise ValueError("aggregate_source_field_required")
        return self


class SubmissionAggregateGroup(Command):
    group: str | None
    value: int | float


class SubmissionAggregateResult(Command):
    start_date: date
    end_date: date
    groups: list[SubmissionAggregateGroup] = Field(max_length=100)


class SubmissionStore(Protocol):
    def create(self, submission: Submission) -> None: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Submission | None: ...
    def snapshot(self, org: UUID, workspace: UUID, identifier: UUID) -> Submission | None: ...
    def save(self, submission: Submission, expected: int) -> bool: ...
    def list_submissions(
        self, org: UUID, workspace: UUID, form: UUID, owner: UUID | None, after: UUID | None
    ) -> list[Submission]: ...
    def aggregate(
        self,
        org: UUID,
        workspace: UUID,
        query: SubmissionAggregateQuery,
    ) -> list[SubmissionAggregateGroup]: ...


class DraftCreated(Submission):
    initialization: RuntimeResult
