from uuid import UUID

from operations.contracts import ServiceError
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.notifications.application.contracts import NoticeSource
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.tasks.application.service import TaskService
from operations.modules.workflows.application.runtime import WorkflowRuntime


class NoticeSources:
    """Owning services decide access; notices never grant access to source records."""

    def __init__(
        self,
        forms: FormService,
        submissions: SubmissionService,
        tasks: TaskService,
        workflows: WorkflowRuntime,
    ) -> None:
        self.forms, self.submissions, self.tasks, self.workflows = (
            forms,
            submissions,
            tasks,
            workflows,
        )

    def source(self, event: OperationalEvent) -> tuple[NoticeSource, UUID]:
        if event.payload.task_id:
            return "task", event.payload.task_id
        if event.payload.workflow_instance_id:
            return "workflow", event.payload.workflow_instance_id
        if event.payload.submission_id:
            return "submission", event.payload.submission_id
        if event.aggregate_type == "project" and event.project_id == event.aggregate_id:
            return "project", event.aggregate_id
        raise ServiceError(422, "notification_source_not_configured")

    def require(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        kind: NoticeSource,
        identifier: UUID,
        intent: UUID | None = None,
    ) -> None:
        if kind == "task":
            # Execution access includes original snapshot and live group/role eligibility.
            row = self.tasks.access(actor, org, workspace, identifier, True, scope_write=False)
            actual_project = row.project_id
        elif kind == "workflow":
            if intent is not None:
                actual_project = self.workflows.notification_access(
                    actor, org, workspace, identifier, intent
                )
            else:
                instance = self.workflows.access(actor, org, workspace, identifier)
                workflow, _ = self.workflows.definition(actor, instance)
                actual_project = workflow.project_id
        elif kind == "submission":
            submission = self.submissions.access(actor, org, workspace, identifier)
            actual_project = self.forms.form(actor, org, workspace, submission.form_id).project_id
        else:
            row_project = self.forms.projects.require_access(
                actor, org, workspace, identifier, "project.read"
            )
            actual_project = row_project.id
        if actual_project != project:
            raise ServiceError(409, "notification_source_scope_mismatch")
