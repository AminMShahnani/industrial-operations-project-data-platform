import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.forms.application.expressions import validate_condition
from operations.modules.forms.application.runtime import components
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.workflows.application.assignments import AssignmentResolver
from operations.modules.workflows.application.contracts import (
    Workflow,
    WorkflowDefinition,
    WorkflowStore,
    WorkflowVersion,
)


def definition_hash(definition: WorkflowDefinition) -> str:
    return hashlib.sha256(
        json.dumps(
            definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class WorkflowService:
    def __init__(
        self, store: WorkflowStore, forms: FormService, assignments: AssignmentResolver
    ) -> None:
        self.store, self.forms, self.assignments = store, forms, assignments

    def require(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        manage: bool = False,
    ) -> None:
        self.forms.require(
            actor, org, workspace, project, "workflow.manage" if manage else "workflow.read", manage
        )

    def event(
        self,
        actor: RequestContext,
        row: Workflow,
        identifier: UUID,
        action: str,
        version: int | None = None,
        reason: str | None = None,
    ) -> None:
        user = self.forms.authorization.user(actor, row.organization_id)
        self.forms.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=row.organization_id,
                actor_id=user.id,
                request_id=actor.request_id,
                correlation_id=actor.correlation_id,
                aggregate_type="workflow",
                aggregate_id=identifier,
                payload=AuditDetails(
                    scope_type="project" if row.project_id else "workspace",
                    scope_id=row.project_id or row.workspace_id,
                    version=version,
                    reason=reason,
                ),
            )
        )

    def get(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        manage: bool = False,
        lock: bool = False,
    ) -> Workflow:
        self.forms.authorization.user(actor, org)
        row = self.store.get(org, workspace, identifier)
        if row is None:
            raise ServiceError(404, "not_found")
        self.require(actor, org, workspace, row.project_id, manage)
        if manage or lock:
            locked = self.store.get(org, workspace, identifier, True)
            if locked is None:
                raise ServiceError(404, "not_found")
            row = locked
        return row

    def check(self, actor: RequestContext, row: Workflow, definition: WorkflowDefinition) -> UUID:
        form, version = self.forms.version(
            actor, row.organization_id, row.workspace_id, definition.form_id, definition.form_number
        )
        if form.project_id != row.project_id or version.state != "published":
            raise ServiceError(422, "workflow_form_scope_or_state")
        fields = components(version.definition)
        keys = {
            field.key
            for field in fields
            if field.kind not in {"table", "repeating_group", "multi_select"}
        }
        user_fields = {field.key for field in fields if field.kind == "user"}
        for node in definition.nodes:
            if node.condition:
                validate_condition(node.condition, keys)
            for target in node.assignments:
                self.assignments.check_target(row, target, user_fields)
            if node.assignments and not any(
                target.kind == "submission_field" for target in node.assignments
            ):
                recipients = self.assignments.resolve(
                    actor,
                    row,
                    node.assignments,
                    node.kind == "approval",
                    notification=node.kind == "notify",
                )
                if not recipients:
                    raise ServiceError(422, "workflow_assignment_has_no_eligible_recipients")
                if node.policy and node.policy.quorum and node.policy.quorum > len(recipients):
                    raise ServiceError(422, "workflow_quorum_exceeds_recipients")
        return version.id

    def create(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        name: str,
        definition: WorkflowDefinition,
    ) -> Workflow:
        self.require(actor, org, workspace, project, True)
        row = Workflow(
            id=uuid7(), organization_id=org, workspace_id=workspace, project_id=project, name=name
        )
        self.check(actor, row, definition)
        self.store.create(row)
        version = WorkflowVersion(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            workflow_id=row.id,
            number=1,
            definition=definition,
        )
        self.store.add_version(version)
        self.event(actor, row, row.id, "workflow.created", 1)
        return row

    def version(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        manage: bool = False,
    ) -> tuple[Workflow, WorkflowVersion]:
        row = self.get(actor, org, workspace, identifier, manage)
        version = self.store.version(org, workspace, identifier, number, manage)
        if version is None:
            raise ServiceError(404, "not_found")
        if version.state == "draft":
            self.require(actor, org, workspace, row.project_id, True)
        return row, version

    def save(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        definition: WorkflowDefinition,
    ) -> WorkflowVersion:
        row, version = self.version(actor, org, workspace, identifier, number, True)
        if version.state != "draft":
            raise ServiceError(409, "immutable_workflow")
        self.check(actor, row, definition)
        updated = version.model_copy(update={"definition": definition, "revision": expected + 1})
        if version.revision != expected or not self.store.save_version(updated, expected):
            raise ServiceError(409, "stale_revision")
        self.event(actor, row, version.id, "workflow.draft.updated", number)
        return updated

    def clone(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        source_number: int,
        number: int,
    ) -> WorkflowVersion:
        row, source = self.version(actor, org, workspace, identifier, source_number, True)
        if self.store.version(org, workspace, identifier, number):
            raise ServiceError(409, "workflow_version_exists")
        version = WorkflowVersion(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            workflow_id=identifier,
            number=number,
            definition=source.definition,
        )
        self.store.add_version(version)
        self.event(actor, row, version.id, "workflow.draft.created", number)
        return version

    def activate(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        dry_run: bool,
        expected_sha256: str | None,
    ) -> WorkflowVersion:
        row, version = self.version(actor, org, workspace, identifier, number, True)
        if version.state != "draft" or version.revision != expected:
            raise ServiceError(409, "workflow_activation_conflict")
        pin = self.check(actor, row, version.definition)
        digest = definition_hash(version.definition)
        updated = version.model_copy(
            update={
                "state": "active",
                "revision": expected + 1,
                "form_version_id": pin,
                "content_sha256": digest,
                "activated_at": datetime.now(UTC),
            }
        )
        if dry_run:
            return updated
        if digest != expected_sha256:
            raise ServiceError(409, "workflow_preview_required")
        if row.active_number:
            previous = self.store.version(org, workspace, identifier, row.active_number)
            if previous and previous.state == "active":
                retired = previous.model_copy(
                    update={"state": "retired", "revision": previous.revision + 1}
                )
                if not self.store.save_version(retired, previous.revision):
                    raise ServiceError(409, "stale_revision")
                self.event(actor, row, previous.id, "workflow.version.retired", previous.number)
        if not self.store.save_version(updated, expected) or not self.store.save(
            row.model_copy(update={"active_number": number, "revision": row.revision + 1}),
            row.revision,
        ):
            raise ServiceError(409, "stale_revision")
        self.event(actor, row, version.id, "workflow.version.activated", number)
        return updated
