from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

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


class SubmissionStore(Protocol):
    def create(self, submission: Submission) -> None: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Submission | None: ...
    def save(self, submission: Submission, expected: int) -> bool: ...
    def list_submissions(
        self, org: UUID, workspace: UUID, form: UUID, owner: UUID | None, after: UUID | None
    ) -> list[Submission]: ...


class DraftCreated(Submission):
    initialization: RuntimeResult
