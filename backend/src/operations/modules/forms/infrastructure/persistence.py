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

from operations.modules.forms.application.contracts import (
    Form,
    FormVersion,
    LibraryArtifact,
    LibraryPin,
)
from operations.platform.database import Base


class FormRow(Base):
    __tablename__ = "forms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        UniqueConstraint("organization_id", "workspace_id", "id", name="uq_forms_scope_identity"),
        Index("ix_forms_scope_cursor", "organization_id", "workspace_id", "project_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int]


class FormVersionRow(Base):
    __tablename__ = "form_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "form_id"],
            ["forms.organization_id", "forms.workspace_id", "forms.id"],
        ),
        UniqueConstraint("organization_id", "form_id", "number", name="uq_form_versions_number"),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_form_versions_scope_identity"
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "form_id",
            "id",
            "number",
            name="uq_form_versions_exact_identity",
        ),
        CheckConstraint(
            "state IN ('draft', 'published', 'deprecated', 'retired')", name="form_state"
        ),
        CheckConstraint("number > 0 AND revision > 0", name="form_version_positive"),
        CheckConstraint(
            "(state = 'draft' AND published_at IS NULL AND content_sha256 IS NULL) OR "
            "(state <> 'draft' AND published_at IS NOT NULL AND content_sha256 IS NOT NULL)",
            name="form_publication_snapshot",
        ),
        Index("ix_form_versions_cursor", "organization_id", "form_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    form_id: Mapped[UUID]
    number: Mapped[int]
    state: Mapped[str] = mapped_column(String(20))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    revision: Mapped[int]
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class LibraryArtifactRow(Base):
    __tablename__ = "form_library_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "code", "version", name="uq_form_library_version"
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", "version", name="uq_form_library_pin"
        ),
        CheckConstraint(
            "kind IN ('field', 'component', 'form') AND version > 0", name="library_kind_version"
        ),
        Index("ix_form_library_cursor", "organization_id", "workspace_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    code: Mapped[str] = mapped_column(String(60))
    version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)


def form_contract(row: FormRow) -> Form:
    return Form(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        name=row.name,
        version=row.version,
    )


def version_contract(row: FormVersionRow) -> FormVersion:
    return FormVersion.model_validate(
        {
            "id": row.id,
            "organization_id": row.organization_id,
            "workspace_id": row.workspace_id,
            "form_id": row.form_id,
            "number": row.number,
            "state": row.state,
            "definition": row.definition,
            "revision": row.revision,
            "published_at": row.published_at,
            "content_sha256": row.content_sha256,
        }
    )


def artifact_contract(row: LibraryArtifactRow) -> LibraryArtifact:
    return LibraryArtifact.model_validate(
        {
            "id": row.id,
            "organization_id": row.organization_id,
            "workspace_id": row.workspace_id,
            "code": row.code,
            "version": row.version,
            "kind": row.kind,
            "definition": row.definition,
        }
    )


class FormRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, form: Form) -> None:
        self.session.add(FormRow(**form.model_dump()))
        self.session.flush()

    def get(self, organization_id: UUID, workspace_id: UUID, form_id: UUID) -> Form | None:
        row = self.session.scalar(
            select(FormRow).where(
                FormRow.organization_id == organization_id,
                FormRow.workspace_id == workspace_id,
                FormRow.id == form_id,
            )
        )
        return form_contract(row) if row else None

    def list_forms(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, after: UUID | None
    ) -> list[Form]:
        query = select(FormRow).where(
            FormRow.organization_id == organization_id,
            FormRow.workspace_id == workspace_id,
            FormRow.project_id == project_id,
        )
        if after:
            query = query.where(FormRow.id > after)
        return [
            form_contract(row)
            for row in self.session.scalars(query.order_by(FormRow.id).limit(101))
        ]

    def add_version(self, version: FormVersion) -> None:
        self.session.add(
            FormVersionRow(
                **version.model_dump(mode="python", exclude={"definition"}),
                definition=version.definition.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def version(self, organization_id: UUID, form_id: UUID, number: int) -> FormVersion | None:
        row = self.session.scalar(
            select(FormVersionRow)
            .where(
                FormVersionRow.organization_id == organization_id,
                FormVersionRow.form_id == form_id,
                FormVersionRow.number == number,
            )
            .with_for_update()
        )
        return version_contract(row) if row else None

    def versions(
        self, organization_id: UUID, form_id: UUID, after: UUID | None
    ) -> list[FormVersion]:
        query = select(FormVersionRow).where(
            FormVersionRow.organization_id == organization_id, FormVersionRow.form_id == form_id
        )
        if after:
            query = query.where(FormVersionRow.id > after)
        return [
            version_contract(row)
            for row in self.session.scalars(query.order_by(FormVersionRow.id).limit(101))
        ]

    def save_version(self, version: FormVersion, expected_revision: int) -> bool:
        result = self.session.execute(
            update(FormVersionRow)
            .where(
                FormVersionRow.organization_id == version.organization_id,
                FormVersionRow.id == version.id,
                FormVersionRow.revision == expected_revision,
            )
            .values(
                state=version.state,
                definition=version.definition.model_dump(mode="json"),
                revision=version.revision,
                published_at=version.published_at,
                content_sha256=version.content_sha256,
            )
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    def add_artifact(self, artifact: LibraryArtifact) -> None:
        self.session.add(
            LibraryArtifactRow(
                **artifact.model_dump(exclude={"definition"}),
                definition=artifact.definition.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def artifact(
        self, organization_id: UUID, workspace_id: UUID, pin: LibraryPin
    ) -> LibraryArtifact | None:
        row = self.session.scalar(
            select(LibraryArtifactRow).where(
                LibraryArtifactRow.organization_id == organization_id,
                LibraryArtifactRow.workspace_id == workspace_id,
                LibraryArtifactRow.id == pin.artifact_id,
                LibraryArtifactRow.version == pin.version,
            )
        )
        return artifact_contract(row) if row else None

    def artifacts(
        self, organization_id: UUID, workspace_id: UUID, after: UUID | None
    ) -> list[LibraryArtifact]:
        query = select(LibraryArtifactRow).where(
            LibraryArtifactRow.organization_id == organization_id,
            LibraryArtifactRow.workspace_id == workspace_id,
        )
        if after:
            query = query.where(LibraryArtifactRow.id > after)
        return [
            artifact_contract(row)
            for row in self.session.scalars(query.order_by(LibraryArtifactRow.id).limit(101))
        ]
