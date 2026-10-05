import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.forms.application.contracts import (
    Component,
    FormValues,
    RuntimeIssue,
    RuntimeResult,
)
from operations.modules.forms.application.runtime import components, public_runtime
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.submissions.application.contracts import (
    DraftCreated,
    SignatureEvidence,
    Submission,
    SubmissionStore,
)


class AttachmentReader(Protocol):
    def require_attachment(
        self,
        org: UUID,
        workspace: UUID,
        submission: UUID,
        owner: UUID,
        identifier: UUID,
        image: bool,
    ) -> None: ...


class SubmissionService:
    def __init__(self, store: SubmissionStore, forms: FormService) -> None:
        self.store, self.forms = store, forms
        self.attachments: AttachmentReader | None = None

    def access(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        write: bool = False,
    ) -> Submission:
        user = self.forms.authorization.user(actor, org)
        row = self.store.get(org, workspace, identifier)
        if not row:
            raise ServiceError(404, "not_found")
        form = self.forms.form(actor, org, workspace, row.form_id)
        permissions = self.forms.permissions(actor, org, workspace, form.project_id)
        if write:
            self.forms.require(actor, org, workspace, form.project_id, "submission.create", True)
            if row.owner_id != user.id:
                raise ServiceError(403, "submission_owner_required")
            if row.state != "draft":
                raise ServiceError(409, "immutable_submission")
        elif row.owner_id != user.id and (
            row.state != "submitted" or "submission.read" not in permissions
        ):
            raise ServiceError(403, "submission_private")
        return row

    def public(self, actor: RequestContext, row: Submission) -> Submission:
        user = self.forms.authorization.user(actor, row.organization_id)
        form, version = self.forms.version(
            actor, row.organization_id, row.workspace_id, row.form_id, row.form_number
        )
        manager = "submission.read" in self.forms.permissions(
            actor, row.organization_id, row.workspace_id, form.project_id
        )
        owner = row.owner_id == user.id

        visible: set[str] = set()

        def filter_fields(
            fields: list[Component], values: Mapping[str, object], prefix: str = ""
        ) -> dict[str, object]:
            output: dict[str, object] = {}
            for field in fields:
                policy = field.permissions.read
                if (policy == "owner" and not owner) or (policy == "manager" and not manager):
                    continue
                visible.add(prefix + field.key)
                value = values.get(field.key)
                if field.children and isinstance(value, list):
                    value = [
                        filter_fields(field.children, item, f"{prefix}{field.key}[{index}].")
                        for index, item in enumerate(value)
                        if isinstance(item, dict)
                    ]
                output[field.key] = value
            return output

        values = FormValues.model_validate(
            {"fields": filter_fields(components(version.definition), row.values.fields)}
        )
        return row.model_copy(
            update={
                "values": values,
                "signatures": [item for item in row.signatures if item.key in visible],
            }
        )

    def create(
        self, actor: RequestContext, org: UUID, workspace: UUID, form_id: UUID, number: int
    ) -> DraftCreated:
        form, version = self.forms.version(actor, org, workspace, form_id, number)
        self.forms.require(actor, org, workspace, form.project_id, "submission.create", True)
        if version.state != "published":
            raise ServiceError(409, "form_not_active")
        user = self.forms.authorization.user(actor, org)
        result = self.forms.evaluate(actor, form, version, FormValues(), False)
        # Missing context is visible in runtime; do not pretend an unavailable default resolved.
        row = Submission(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            form_id=form_id,
            form_version_id=version.id,
            form_number=number,
            owner_id=user.id,
            values=result.values,
        )
        self.store.create(row)
        self.forms.event(actor, form, "submission.draft.created", row.id, number)
        return DraftCreated(**row.model_dump(), initialization=public_runtime(result))

    def validate(
        self, actor: RequestContext, row: Submission, values: FormValues, complete: bool
    ) -> RuntimeResult:
        form, version = self.forms.version(
            actor, row.organization_id, row.workspace_id, row.form_id, row.form_number
        )
        # Deprecation permits existing drafts; retirement prohibits new writes.
        if version.id != row.form_version_id or version.state == "retired":
            raise ServiceError(409, "form_retired")
        result = self.forms.evaluate(actor, form, version, values, complete, False, row.values)
        issues = list(result.issues)

        def check(field: Component, value: object, key: str) -> None:
            if value is None:
                return
            if field.children and isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        for child in field.children:
                            check(child, item.get(child.key), f"{key}[{index}].{child.key}")
                return
            if not isinstance(value, str):
                return
            try:
                if field.kind == "master_data" and field.source and field.source.type_id:
                    self.forms.master_data.references.require(
                        row.organization_id,
                        row.workspace_id,
                        form.project_id,
                        UUID(value),
                        type_id=field.source.type_id,
                    )
                elif field.kind == "user":
                    user = self.forms.authorization.identities.by_id(
                        row.organization_id, UUID(value)
                    )
                    if not user or not self.forms.eligible_user(actor, form, user):
                        raise ServiceError(422, "invalid_user_reference")
                elif field.kind == "department":
                    self.forms.projects.groups.active_department(
                        row.organization_id, row.workspace_id, UUID(value)
                    )
                elif field.kind == "project":
                    self.forms.projects.require_access(
                        actor, row.organization_id, row.workspace_id, UUID(value), "project.read"
                    )
                elif field.kind in {"file", "image"}:
                    if not self.attachments:
                        raise ServiceError(503, "attachment_service_unavailable")
                    self.attachments.require_attachment(
                        row.organization_id,
                        row.workspace_id,
                        row.id,
                        row.owner_id,
                        UUID(value),
                        field.kind == "image",
                    )
            except (ServiceError, ValueError) as error:
                issues.append(
                    RuntimeIssue(
                        key=key,
                        code=error.code if isinstance(error, ServiceError) else "invalid_reference",
                    )
                )

        for field in components(version.definition):
            check(field, result.values.fields.get(field.key), field.key)
        return result.model_copy(update={"issues": issues})

    def save(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        values: FormValues,
        expected: int,
    ) -> Submission:
        row = self.access(actor, org, workspace, identifier, True)
        result = self.validate(actor, row, values, False)
        if result.issues:
            raise ServiceError(422, "invalid_submission_values")
        updated = row.model_copy(update={"values": result.values, "revision": expected + 1})
        if row.revision != expected or not self.store.save(updated, expected):
            raise ServiceError(409, "version_conflict")
        form = self.forms.form(actor, org, workspace, row.form_id)
        self.forms.event(actor, form, "submission.draft.saved", identifier, updated.revision)
        return updated

    def submit(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
        key: UUID,
        reason: str,
    ) -> Submission:
        row = self.access(actor, org, workspace, identifier)
        user = self.forms.authorization.user(actor, org)
        form = self.forms.form(actor, org, workspace, row.form_id)
        self.forms.require(actor, org, workspace, form.project_id, "submission.create", True)
        if row.owner_id != user.id:
            raise ServiceError(403, "submission_owner_required")
        if row.state == "submitted":
            if row.submit_key == key:
                return row
            raise ServiceError(409, "immutable_submission")
        # Server-owned formulas are recalculated; strip previously computed values.
        _, version = self.forms.version(actor, org, workspace, row.form_id, row.form_number)

        def editable(fields: list[Component], values: Mapping[str, object]) -> dict[str, object]:
            output: dict[str, object] = {}
            for field in fields:
                if (
                    field.kind in {"calculated", "display"}
                    or (field.permissions.write == "manager" or field.permissions.read == "manager")
                    and "form.manage"
                    not in self.forms.permissions(actor, org, workspace, form.project_id)
                ):
                    continue
                value = values.get(field.key)
                if field.children and isinstance(value, list):
                    value = [
                        editable(field.children, item) for item in value if isinstance(item, dict)
                    ]
                output[field.key] = value
            return output

        values = FormValues.model_validate(
            {"fields": editable(components(version.definition), row.values.fields)}
        )
        result = self.validate(actor, row, values, True)
        if result.issues:
            raise ServiceError(422, "submission_validation_failed")
        now = datetime.now(UTC)
        evidence: list[SignatureEvidence] = []

        def signatures(fields: list[Component], values: Mapping[str, object], prefix: str) -> None:
            for field in fields:
                value = values.get(field.key)
                path = prefix + field.key
                if field.kind == "signature" and value:
                    evidence.append(
                        SignatureEvidence(
                            key=path, signer_id=user.id, occurred_at=now, reason=reason
                        )
                    )
                elif field.children and isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, dict):
                            signatures(field.children, item, f"{path}[{index}].")

        signatures(components(version.definition), result.values.fields, "")
        digest = hashlib.sha256(result.values.model_dump_json().encode()).hexdigest()
        updated = row.model_copy(
            update={
                "state": "submitted",
                "values": result.values,
                "revision": expected + 1,
                "submitted_at": now,
                "submit_key": key,
                "content_sha256": digest,
                "signatures": evidence,
            }
        )
        if row.revision != expected or not self.store.save(updated, expected):
            raise ServiceError(409, "version_conflict")
        self.forms.event(actor, form, "submission.submitted", identifier, updated.revision)
        return updated
