from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.submissions.application.contracts import Submission
from operations.platform.database import Base


class SubmissionRow(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_id"],
            ["forms.organization_id", "forms.workspace_id", "forms.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_id", "form_version_id", "form_number"],
            [
                "form_versions.organization_id",
                "form_versions.workspace_id",
                "form_versions.form_id",
                "form_versions.id",
                "form_versions.number",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["users.organization_id", "users.id"]
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_submissions_scope_identity"
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", "owner_id", name="uq_submissions_scope_owner"
        ),
        UniqueConstraint("organization_id", "submit_key", name="uq_submissions_submit_key"),
        CheckConstraint(
            "state IN ('draft', 'submitted') AND revision > 0 AND form_number > 0",
            name="submission_lifecycle",
        ),
        CheckConstraint(
            "(state='draft' AND submitted_at IS NULL AND submit_key IS NULL "
            "AND content_sha256 IS NULL) OR "
            "(state='submitted' AND submitted_at IS NOT NULL AND submit_key IS NOT NULL "
            "AND content_sha256 IS NOT NULL)",
            name="submission_snapshot",
        ),
        Index(
            "ix_submissions_scope_state_cursor",
            "organization_id",
            "workspace_id",
            "form_id",
            "state",
            "id",
        ),
        Index(
            "ix_submissions_scope_owner_cursor",
            "organization_id",
            "workspace_id",
            "form_id",
            "owner_id",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    form_id: Mapped[UUID]
    form_version_id: Mapped[UUID]
    form_number: Mapped[int]
    owner_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(20))
    values: Mapped[dict[str, object]] = mapped_column(JSONB)
    revision: Mapped[int]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submit_key: Mapped[UUID | None]
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    signatures: Mapped[list[dict[str, object]]] = mapped_column(JSONB)


def contract(row: SubmissionRow) -> Submission:
    return Submission.model_validate({name: getattr(row, name) for name in Submission.model_fields})


class SubmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(self, org: UUID, workspace: UUID, identifier: UUID) -> Submission | None:
        row = self.session.scalar(
            select(SubmissionRow).where(
                SubmissionRow.organization_id == org,
                SubmissionRow.workspace_id == workspace,
                SubmissionRow.id == identifier,
                SubmissionRow.state == "submitted",
            )
        )
        return contract(row) if row else None

    def create(self, submission: Submission) -> None:
        self.session.add(
            SubmissionRow(
                **submission.model_dump(exclude={"values", "signatures"}),
                values=submission.values.model_dump(mode="json"),
                signatures=[item.model_dump(mode="json") for item in submission.signatures],
            )
        )
        self.session.flush()

    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Submission | None:
        row = self.session.scalar(
            select(SubmissionRow)
            .where(
                SubmissionRow.organization_id == org,
                SubmissionRow.workspace_id == workspace,
                SubmissionRow.id == identifier,
            )
            .with_for_update()
        )
        return contract(row) if row else None

    def save(self, submission: Submission, expected: int) -> bool:
        result = self.session.execute(
            update(SubmissionRow)
            .where(
                SubmissionRow.organization_id == submission.organization_id,
                SubmissionRow.id == submission.id,
                SubmissionRow.revision == expected,
            )
            .values(
                values=submission.values.model_dump(mode="json"),
                state=submission.state,
                revision=submission.revision,
                submitted_at=submission.submitted_at,
                submit_key=submission.submit_key,
                content_sha256=submission.content_sha256,
                signatures=[item.model_dump(mode="json") for item in submission.signatures],
            )
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def list_submissions(
        self, org: UUID, workspace: UUID, form: UUID, owner: UUID | None, after: UUID | None
    ) -> list[Submission]:
        query = select(SubmissionRow).where(
            SubmissionRow.organization_id == org,
            SubmissionRow.workspace_id == workspace,
            SubmissionRow.form_id == form,
        )
        if owner:
            query = query.where(SubmissionRow.owner_id == owner)
        else:
            query = query.where(SubmissionRow.state == "submitted")
        if after:
            query = query.where(SubmissionRow.id > after)
        return [
            contract(row)
            for row in self.session.scalars(query.order_by(SubmissionRow.id).limit(101))
        ]
