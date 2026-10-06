import hashlib
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.contracts import ServiceError
from operations.modules.files.application.contracts import Attachment
from operations.platform.database import Base


class FileRow(Base):
    __tablename__ = "files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"], ["users.organization_id", "users.id"]
        ),
        CheckConstraint("size > 0 AND size <= 5242880", name="attachment_size"),
        Index(
            "ix_files_scope_submission", "organization_id", "workspace_id", "submission_id", "id"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    submission_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(240), unique=True)


class FileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, attachment: Attachment) -> None:
        self.lock_key(attachment.object_key, wait=True)
        self.session.add(FileRow(**attachment.model_dump()))
        self.session.flush()

    def lock_key(self, key: str, wait: bool = False) -> bool:
        # Upload and reconciliation share a transaction-held lock even before a row exists.
        identifier = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
        if wait:
            self.session.execute(select(func.pg_advisory_xact_lock(identifier)))
            return True
        if self.session.connection().get_isolation_level() != "READ COMMITTED":
            raise ServiceError(503, "cleanup_isolation_not_supported")
        return bool(self.session.scalar(select(func.pg_try_advisory_xact_lock(identifier))))

    def referenced(self, org: UUID, key: str) -> bool:
        return (
            self.session.scalar(
                select(FileRow.id).where(FileRow.organization_id == org, FileRow.object_key == key)
            )
            is not None
        )

    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Attachment | None:
        row = self.session.scalar(
            select(FileRow).where(
                FileRow.organization_id == org,
                FileRow.workspace_id == workspace,
                FileRow.id == identifier,
            )
        )
        return (
            Attachment.model_validate(
                {name: getattr(row, name) for name in Attachment.model_fields}
            )
            if row
            else None
        )
