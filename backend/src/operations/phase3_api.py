import base64
import binascii
from typing import Literal
from uuid import UUID, uuid7

from fastapi import APIRouter
from pydantic import EmailStr, Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command, ServiceError
from operations.modules.files.application.contracts import Attachment
from operations.modules.forms.application.contracts import (
    Form,
    FormDefinition,
    FormValues,
    FormVersion,
    LibraryArtifact,
    LookupPage,
    RuntimeResult,
)
from operations.modules.forms.application.runtime import public_runtime
from operations.modules.submissions.application.contracts import DraftCreated, Submission

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}",
    tags=["forms and submissions"],
)
FORM = "/forms/{form_id}"
VERSION = FORM + "/versions/{number}"
SUBMISSION = "/submissions/{submission_id}"


class FormCreate(Command):
    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    definition: FormDefinition
    template_id: UUID | None = None
    template_version: int | None = Field(default=None, ge=1)


class DefinitionSave(Command):
    definition: FormDefinition
    expected_revision: int = Field(ge=1)


class Publish(Command):
    expected_revision: int = Field(ge=1)
    dry_run: bool = True
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Clone(Command):
    source_number: int = Field(ge=1)
    number: int = Field(ge=1)


class VersionLifecycle(Command):
    dry_run: bool = True
    reason: str = Field(min_length=1, max_length=500)
    state: Literal["deprecated", "retired"]
    expected_revision: int = Field(ge=1)


class Preview(Command):
    values: FormValues = Field(default_factory=FormValues)
    complete: bool = True


class FormPage(Command):
    items: list[Form]
    next_cursor: UUID | None


class VersionPage(Command):
    items: list[FormVersion]
    next_cursor: UUID | None


class LibraryCreate(Command):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")
    version: int = Field(ge=1)
    kind: Literal["field", "component", "form"]
    definition: FormDefinition


class LibraryPage(Command):
    items: list[LibraryArtifact]
    next_cursor: UUID | None


class DraftCreate(Command):
    form_id: UUID
    number: int = Field(ge=1)


class DraftSave(Command):
    values: FormValues
    expected_revision: int = Field(ge=1)


class Submit(Command):
    expected_revision: int = Field(ge=1)
    idempotency_key: UUID
    reason: str = Field(min_length=1, max_length=500)


class SubmissionPage(Command):
    items: list[Submission]
    next_cursor: UUID | None


class Upload(Command):
    name: str = Field(min_length=1, max_length=120)
    content_type: Literal["text/plain", "application/pdf", "image/png", "image/jpeg"]
    content_base64: str = Field(min_length=1, max_length=6990508)


class Download(Command):
    url: str
    expires_in: Literal[60] = 60


@router.post("/forms", response_model=Form, status_code=201)
def create_form(
    organization_id: UUID,
    workspace_id: UUID,
    body: FormCreate,
    actor: Context,
    service: ServiceDependency,
) -> Form:
    definition = body.definition
    if body.template_id:
        from operations.modules.forms.application.contracts import LibraryPin

        service.forms.require(
            actor, organization_id, workspace_id, body.project_id, "form.manage", True
        )
        artifact = service.forms.store.artifact(
            organization_id,
            workspace_id,
            LibraryPin(artifact_id=body.template_id, version=body.template_version or 1),
        )
        if not artifact or artifact.kind != "form":
            raise ServiceError(422, "invalid_form_template_pin")
        definition = artifact.definition
    return service.forms.create(
        actor, organization_id, workspace_id, body.project_id, body.name, definition
    )


@router.get("/forms", response_model=FormPage)
def list_forms(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    service: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> FormPage:
    rows, next_cursor = service.forms.list_forms(
        actor, organization_id, workspace_id, project_id, cursor
    )
    return FormPage(items=rows, next_cursor=next_cursor)


@router.get(FORM + "/permissions", response_model=list[str])
def form_permissions(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> list[str]:
    form = service.forms.form(actor, organization_id, workspace_id, form_id)
    return sorted(service.forms.permissions(actor, organization_id, workspace_id, form.project_id))


@router.get(FORM + "/versions", response_model=VersionPage)
def list_versions(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
) -> VersionPage:
    form = service.forms.form(actor, organization_id, workspace_id, form_id)
    rows = service.forms.store.versions(organization_id, form_id, cursor)
    manager = "form.manage" in service.forms.permissions(
        actor, organization_id, workspace_id, form.project_id
    )
    visible = [row for row in rows[:100] if manager or row.state != "draft"]
    return VersionPage(
        items=[
            service.forms.public_version(actor, organization_id, workspace_id, form_id, row.number)
            for row in visible
        ],
        next_cursor=rows[99].id if len(rows) > 100 else None,
    )


@router.get(VERSION, response_model=FormVersion)
def get_version(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    actor: Context,
    service: ServiceDependency,
) -> FormVersion:
    return service.forms.public_version(actor, organization_id, workspace_id, form_id, number)


@router.put(VERSION, response_model=FormVersion)
def save_version(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    body: DefinitionSave,
    actor: Context,
    service: ServiceDependency,
) -> FormVersion:
    return service.forms.save(
        actor,
        organization_id,
        workspace_id,
        form_id,
        number,
        body.definition,
        body.expected_revision,
    )


@router.post(FORM + "/versions", response_model=FormVersion, status_code=201)
def clone_version(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    body: Clone,
    actor: Context,
    service: ServiceDependency,
) -> FormVersion:
    return service.forms.clone(
        actor, organization_id, workspace_id, form_id, body.source_number, body.number
    )


@router.post(VERSION + "/publish", response_model=FormVersion)
def publish_version(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    body: Publish,
    actor: Context,
    service: ServiceDependency,
) -> FormVersion:
    return service.forms.publish(
        actor,
        organization_id,
        workspace_id,
        form_id,
        number,
        body.expected_revision,
        body.dry_run,
        body.expected_sha256,
    )


@router.post(VERSION + "/lifecycle", response_model=FormVersion)
def version_lifecycle(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    body: VersionLifecycle,
    actor: Context,
    service: ServiceDependency,
) -> FormVersion:
    return service.forms.lifecycle(
        actor,
        organization_id,
        workspace_id,
        form_id,
        number,
        body.state,
        body.expected_revision,
        body.dry_run,
        body.reason,
    )


@router.post(VERSION + "/preview", response_model=RuntimeResult)
def preview_version(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    body: Preview,
    actor: Context,
    service: ServiceDependency,
) -> RuntimeResult:
    form, version = service.forms.version(actor, organization_id, workspace_id, form_id, number)
    return public_runtime(service.forms.evaluate(actor, form, version, body.values, body.complete))


@router.post("/form-library", response_model=LibraryArtifact, status_code=201)
def create_library(
    organization_id: UUID,
    workspace_id: UUID,
    body: LibraryCreate,
    actor: Context,
    service: ServiceDependency,
) -> LibraryArtifact:
    return service.forms.library(
        actor,
        LibraryArtifact(
            id=uuid7(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            **body.model_dump(),
        ),
    )


@router.get("/form-library", response_model=LibraryPage)
def list_library(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
    project_id: UUID | None = None,
) -> LibraryPage:
    service.forms.require(actor, organization_id, workspace_id, project_id, "form.manage")
    rows = service.forms.store.artifacts(organization_id, workspace_id, cursor)
    return LibraryPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.post("/submissions", response_model=DraftCreated, status_code=201)
def create_draft(
    organization_id: UUID,
    workspace_id: UUID,
    body: DraftCreate,
    actor: Context,
    service: ServiceDependency,
) -> Submission:
    return service.submissions.public(
        actor,
        service.submissions.create(actor, organization_id, workspace_id, body.form_id, body.number),
    )


@router.get(SUBMISSION, response_model=Submission)
def get_submission(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> Submission:
    return service.submissions.public(
        actor, service.submissions.access(actor, organization_id, workspace_id, submission_id)
    )


@router.get(FORM + "/submissions", response_model=SubmissionPage)
def list_submissions(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    actor: Context,
    service: ServiceDependency,
    cursor: UUID | None = None,
    own: bool = True,
) -> SubmissionPage:
    form = service.forms.form(actor, organization_id, workspace_id, form_id)
    user = service.authorization.user(actor, organization_id)
    if not own:
        service.forms.require(
            actor, organization_id, workspace_id, form.project_id, "submission.read"
        )
    rows = service.submissions.store.list_submissions(
        organization_id, workspace_id, form_id, user.id if own else None, cursor
    )
    return SubmissionPage(
        items=[service.submissions.public(actor, row) for row in rows[:100]],
        next_cursor=rows[99].id if len(rows) > 100 else None,
    )


@router.put(SUBMISSION, response_model=Submission)
def save_draft(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    body: DraftSave,
    actor: Context,
    service: ServiceDependency,
) -> Submission:
    return service.submissions.public(
        actor,
        service.submissions.save(
            actor, organization_id, workspace_id, submission_id, body.values, body.expected_revision
        ),
    )


@router.post(SUBMISSION + "/validate", response_model=RuntimeResult)
def validate_draft(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    body: Preview,
    actor: Context,
    service: ServiceDependency,
) -> RuntimeResult:
    row = service.submissions.access(actor, organization_id, workspace_id, submission_id, True)
    return public_runtime(service.submissions.validate(actor, row, body.values, body.complete))


@router.post(SUBMISSION + "/submit", response_model=Submission)
def submit_draft(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    body: Submit,
    actor: Context,
    service: ServiceDependency,
) -> Submission:
    return service.submissions.public(
        actor,
        service.submissions.submit(
            actor,
            organization_id,
            workspace_id,
            submission_id,
            body.expected_revision,
            body.idempotency_key,
            body.reason,
        ),
    )


@router.post(SUBMISSION + "/files", response_model=Attachment, status_code=201)
def upload_file(
    organization_id: UUID,
    workspace_id: UUID,
    submission_id: UUID,
    body: Upload,
    actor: Context,
    service: ServiceDependency,
) -> Attachment:
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ServiceError(422, "invalid_file_encoding") from error
    return service.files.upload(
        actor, organization_id, workspace_id, submission_id, body.name, body.content_type, data
    )


@router.post("/files/{file_id}/download", response_model=Download)
def download_file(
    organization_id: UUID,
    workspace_id: UUID,
    file_id: UUID,
    actor: Context,
    service: ServiceDependency,
) -> Download:
    return Download(url=service.files.download(actor, organization_id, workspace_id, file_id))


@router.get(VERSION + "/lookups/{field_key}", response_model=LookupPage)
def form_lookup(
    organization_id: UUID,
    workspace_id: UUID,
    form_id: UUID,
    number: int,
    field_key: str,
    actor: Context,
    service: ServiceDependency,
    email: EmailStr | None = None,
    cursor: UUID | None = None,
) -> LookupPage:
    return service.forms.lookup(
        actor, organization_id, workspace_id, form_id, number, field_key, email, cursor
    )
