"""Industry-neutral actions use the target module's authorized application services."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.automation.application.contracts import (
    AutomationAction,
    MetadataAction,
    RecordAction,
    Rule,
    Run,
    TaskAction,
    WorkflowAction,
)
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.forms.application.contracts import FormValues
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.master_data.application.contracts import DataRecord, RecordStatus
from operations.modules.scheduling.application.contracts import Recurrence, ScheduleDefinition
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.tasks.application.service import TaskService
from operations.modules.workflows.application.runtime import WorkflowRuntime


class AdditionalActions(Protocol):
    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None: ...
    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None: ...


class UnavailableActions:
    """Fail closed while remaining Phase 6 adapters are being implemented."""

    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None:
        raise ServiceError(422, "automation_action_not_configured")

    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None:
        raise ServiceError(422, "automation_action_not_configured")


class ApplicationActions:
    def __init__(
        self,
        forms: FormService,
        submissions: SubmissionService,
        tasks: TaskService,
        workflows: WorkflowRuntime,
        additional: AdditionalActions,
    ) -> None:
        self.forms, self.submissions, self.tasks = forms, submissions, tasks
        self.workflows, self.additional = workflows, additional

    def schedule(
        self, action: TaskAction, at: OperationalEvent | None = None
    ) -> ScheduleDefinition:
        if action.form_id is None or action.form_number is None:
            raise ServiceError(422, "automation_form_task_pin_required")
        # Validation uses a fixed aware anchor; execution uses the immutable event time.
        return ScheduleDefinition(
            form_id=action.form_id,
            form_number=action.form_number,
            recurrence=Recurrence(
                kind="one_time", at=at.occurred_at if at else datetime(2000, 1, 1, tzinfo=UTC)
            ),
            assignments=action.assignments,
            due_after_seconds=action.due_seconds,
        )

    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None:
        org, workspace, project = rule.organization_id, rule.workspace_id, rule.project_id
        if isinstance(action, MetadataAction):
            if project is None:
                raise ServiceError(422, "automation_project_metadata_required")
            self.forms.require(actor, org, workspace, project, "project.manage", True)
        elif isinstance(action, RecordAction):
            definition = self.forms.master_data.definition(actor, org, action.type_id, True)
            if definition.workspace_id != workspace or definition.project_id != project:
                raise ServiceError(422, "automation_record_scope_mismatch")
            self.forms.master_data.validate(
                definition,
                DataRecord(
                    id=uuid7(),
                    organization_id=org,
                    type_id=action.type_id,
                    code="automation_preview",
                    name=action.name,
                    status=RecordStatus.ACTIVE,
                    valid_from=None,
                    valid_until=None,
                    values=action.values,
                ),
            )
        elif isinstance(action, TaskAction) and action.form_id is not None:
            self.tasks.schedules.require(actor, org, workspace, project, True)
            self.tasks.schedules.check(actor, org, workspace, project, self.schedule(action))
        elif isinstance(action, WorkflowAction):
            workflow, version = self.workflows.workflows.version(
                actor, org, workspace, action.workflow_id, action.workflow_number, True
            )
            if (
                workflow.project_id != project
                or version.state != "active"
                or workflow.active_number != version.number
            ):
                raise ServiceError(422, "automation_workflow_scope_or_state")
        else:
            self.additional.validate(actor, rule, action)

    def values(self, actor: RequestContext, event: OperationalEvent) -> FormValues:
        org, workspace = event.organization_id, event.workspace_id
        if workspace is None:
            raise ServiceError(422, "automation_workspace_source_required")
        payload = event.payload
        values = FormValues(
            fields={
                "event_type": event.type,
                "project_phase": payload.phase,
                "form_number": payload.form_number,
                "subject_user_id": str(payload.subject_user_id)
                if payload.subject_user_id
                else None,
            }
        )
        if payload.task_id:
            task = self.tasks.access(actor, org, workspace, payload.task_id)
            if task.project_id != event.project_id:
                raise ServiceError(409, "automation_source_scope_mismatch")
        if payload.workflow_instance_id:
            instance = self.workflows.access(actor, org, workspace, payload.workflow_instance_id)
            workflow, _ = self.workflows.definition(actor, instance)
            if workflow.project_id != event.project_id:
                raise ServiceError(409, "automation_source_scope_mismatch")
        if payload.submission_id:
            submission = self.submissions.access(actor, org, workspace, payload.submission_id)
            form = self.forms.form(actor, org, workspace, submission.form_id)
            if (
                form.project_id != event.project_id
                or submission.form_id != payload.form_id
                or submission.form_number != payload.form_number
            ):
                raise ServiceError(409, "automation_source_form_mismatch")
            public = self.submissions.public(actor, submission)
            for key, value in public.values.fields.items():
                if len(key) <= 55 and (value is None or isinstance(value, str | int | bool)):
                    values.fields["form_" + key] = value
        elif event.aggregate_type == "project" and event.project_id:
            self.forms.projects.require_access(
                actor, org, workspace, event.project_id, "project.read"
            )
        if payload.master_data_type_id:
            definition = self.forms.master_data.definition(actor, org, payload.master_data_type_id)
            if definition.workspace_id != workspace or definition.project_id != event.project_id:
                raise ServiceError(409, "automation_source_scope_mismatch")
        return values

    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None:
        org, workspace, project = rule.organization_id, rule.workspace_id, rule.project_id
        if isinstance(action, MetadataAction):
            if project is None:
                raise ServiceError(422, "automation_project_metadata_required")
            row = self.forms.projects.require_access(
                actor, org, workspace, project, "project.manage"
            )
            self.forms.projects.update(
                actor,
                org,
                workspace,
                project,
                row.name,
                row.context.model_copy(update={"description": action.description}),
                row.version,
            )
            return row.id
        if isinstance(action, RecordAction):
            record = self.forms.master_data.create_record(
                actor,
                org,
                action.type_id,
                f"automation_{run.id.hex}_{position}",
                action.name,
                RecordStatus.ACTIVE,
                None,
                None,
                action.values,
            )
            return record.id
        if isinstance(action, TaskAction) and action.form_id is not None:
            schedule = self.tasks.schedules.create(
                actor, org, workspace, project, action.name, self.schedule(action, event)
            )
            preview = self.tasks.schedules.activate(
                actor, org, workspace, schedule.id, 1, 1, True, None
            )
            self.tasks.schedules.activate(
                actor, org, workspace, schedule.id, 1, 1, False, preview.content_sha256
            )
            _, count = self.tasks.materialize(
                actor,
                org,
                workspace,
                schedule.id,
                event.occurred_at,
                event.occurred_at + timedelta(seconds=1),
                False,
            )
            if count == 0:
                raise ServiceError(409, "automation_task_materialization_empty")
            return schedule.id
        if isinstance(action, WorkflowAction):
            if event.payload.submission_id is None:
                raise ServiceError(422, "automation_workflow_submitted_source_required")
            instance = self.workflows.start_pinned(
                actor,
                org,
                workspace,
                event.payload.submission_id,
                action.workflow_id,
                action.workflow_number,
                project,
            )
            return instance.id
        return self.additional.execute(actor, rule, event, run, position, action)
