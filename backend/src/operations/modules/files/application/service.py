import hashlib
import logging
import re
from collections.abc import Mapping
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.files.application.contracts import (
    Attachment,
    FileStore,
    MalwareScanner,
    PrivateStorage,
)
from operations.modules.forms.application.contracts import Component
from operations.modules.forms.application.runtime import components
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.submissions.application.service import SubmissionService


class FileService:
    def __init__(
        self,
        store: FileStore,
        submissions: SubmissionService,
        scanner: MalwareScanner,
        storage: PrivateStorage,
    ) -> None:
        self._created_keys: list[str] = []
        self.store, self.submissions, self.scanner, self.storage = (
            store,
            submissions,
            scanner,
            storage,
        )

    def upload(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        submission: UUID,
        name: str,
        content_type: str,
        data: bytes,
    ) -> Attachment:
        parent = self.submissions.access(actor, org, workspace, submission, True)
        form, version = self.submissions.forms.version(
            actor, org, workspace, parent.form_id, parent.form_number
        )
        manager = "form.manage" in self.submissions.forms.permissions(
            actor, org, workspace, form.project_id
        )
        candidates = [
            field
            for field in components(version.definition)
            if (field.permissions.read != "manager" or manager)
            and (field.permissions.write != "manager" or manager)
        ]
        candidates = candidates + [child for field in candidates for child in field.children]
        if not any(
            field.kind in {"file", "image"}
            and (field.kind == "file" or content_type.startswith("image/"))
            and (field.permissions.write != "manager" or manager)
            and (field.permissions.read != "manager" or manager)
            for field in candidates
        ):
            raise ServiceError(403, "form_attachment_not_allowed")
        if not 0 < len(data) <= 5 * 1024 * 1024:
            raise ServiceError(413, "attachment_size_limit")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.()-]{0,119}", name):
            raise ServiceError(422, "unsafe_file_name")
        signatures = {
            "application/pdf": b"%PDF-",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/jpeg": b"\xff\xd8\xff",
        }
        if content_type == "text/plain":
            try:
                text = data.decode("utf-8")
            except UnicodeError as error:
                raise ServiceError(422, "invalid_file_content") from error
            if "\x00" in text or text.lstrip().startswith(("<", "<?", "#!")):
                raise ServiceError(422, "invalid_file_content")
        elif content_type not in signatures or not data.startswith(signatures[content_type]):
            raise ServiceError(422, "invalid_file_content")
        # No object is made downloadable before a positive trusted scan.
        if not self.scanner.clean(data):
            raise ServiceError(422, "malware_detected")
        identifier = uuid7()
        key = f"organizations/{org}/workspaces/{workspace}/submissions/{submission}/{identifier}"
        attachment = Attachment(
            id=identifier,
            organization_id=org,
            workspace_id=workspace,
            submission_id=submission,
            owner_id=parent.owner_id,
            name=name,
            content_type=content_type,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            object_key=key,
        )
        self._created_keys.append(key)
        self.storage.put(key, data, content_type)
        self.store.add(attachment)
        form = self.submissions.forms.form(actor, org, workspace, parent.form_id)
        self.submissions.forms.event(actor, form, "file.uploaded", identifier)
        return attachment

    def compensate_rollback(self) -> None:
        for key in self._created_keys:
            try:
                self.storage.delete(key)
            except ServiceError:
                # No object names, uploaded content or signed credentials in logs.
                logging.getLogger("operations.files").warning("file.rollback.cleanup_failed")
        self._created_keys.clear()

    def require_attachment(
        self,
        org: UUID,
        workspace: UUID,
        submission: UUID,
        owner: UUID,
        identifier: UUID,
        image: bool,
    ) -> None:
        row = self.store.get(org, workspace, identifier)
        if (
            not row
            or row.submission_id != submission
            or row.owner_id != owner
            or (image and not row.content_type.startswith("image/"))
        ):
            raise ServiceError(422, "invalid_attachment_reference")

    def download(self, actor: RequestContext, org: UUID, workspace: UUID, identifier: UUID) -> str:
        row = self.store.get(org, workspace, identifier)
        if not row:
            raise ServiceError(404, "not_found")
        parent = self.submissions.public(
            actor, self.submissions.access(actor, org, workspace, row.submission_id)
        )
        # Managers may only download files present in the submitted snapshot.
        user = self.submissions.forms.authorization.user(actor, org)
        _, version = self.submissions.forms.version(
            actor, org, workspace, parent.form_id, parent.form_number
        )

        def references(fields: list[Component], values: Mapping[str, object]) -> set[str]:
            result: set[str] = set()
            for field in fields:
                value = values.get(field.key)
                if field.kind in {"file", "image"} and isinstance(value, str):
                    result.add(value)
                elif field.children and isinstance(value, list):
                    for row in value:
                        if isinstance(row, dict):
                            result.update(references(field.children, row))
            return result

        if parent.owner_id != user.id and str(identifier) not in references(
            components(version.definition), parent.values.fields
        ):
            raise ServiceError(403, "attachment_not_in_snapshot")
        form = self.submissions.forms.form(actor, org, workspace, parent.form_id)
        self.submissions.forms.event(actor, form, "file.download.authorized", identifier)
        return self.storage.signed_download(row.object_key, row.name, row.content_type)
