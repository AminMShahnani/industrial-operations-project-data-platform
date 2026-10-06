from uuid import UUID

from operations.modules.forms.application.contracts import Cell, DefaultContext
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.workflows.application.contracts import RuntimeStore


class WorkflowDefaults:
    def __init__(
        self, shifts: DefaultContext, store: RuntimeStore, submissions: SubmissionService
    ) -> None:
        self.shifts, self.store, self.submissions = shifts, store, submissions

    def shift(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, user_id: UUID
    ) -> str | None:
        return self.shifts.shift(organization_id, workspace_id, project_id, user_id)

    def previous_approved(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        form_id: UUID,
        owner_id: UUID,
        field_key: str,
    ) -> Cell:
        identifier = self.store.approved_submission(
            organization_id, workspace_id, form_id, owner_id
        )
        if identifier is None:
            return None
        row = self.submissions.snapshot(organization_id, workspace_id, identifier)
        if row.owner_id != owner_id or row.form_id != form_id:
            return None
        value = row.values.fields.get(field_key)
        return value if value is None or isinstance(value, str | int | bool) else None
