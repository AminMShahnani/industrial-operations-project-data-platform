from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.forms.application.expressions import condition_matches
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.submissions.application.contracts import Submission
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.tasks.application.service import TaskService
from operations.modules.workflows.application.contracts import (
    AssignedStep,
    RuntimeStore,
    Workflow,
    WorkflowAction,
    WorkflowInstance,
    WorkflowNotification,
    WorkflowRevision,
    WorkflowStep,
    WorkflowVersion,
)
from operations.modules.workflows.application.service import WorkflowService
from operations.modules.workflows.domain.graph import (
    approval_complete,
    eligible_approvers,
    require_next_approver,
)


class WorkflowRuntime:
    def __init__(
        self, store: RuntimeStore, workflows: WorkflowService, submissions: SubmissionService
    ) -> None:
        self.store, self.workflows, self.submissions = store, workflows, submissions
        self.tasks: WorkflowTasks | None = None

    def root_submission(self, org: UUID, workspace: UUID, submission: UUID) -> UUID:
        revision = self.store.revision_by_submission(org, workspace, submission)
        return revision.root_submission_id if revision else submission

    def sync_tasks(self, actor: RequestContext, row: WorkflowInstance) -> None:
        if self.tasks:
            state = {
                "active": "awaiting_review",
                "approved": "approved",
                "closed": "submitted",
                "returned": "returned",
                "rejected": "returned",
            }[row.state]
            self.tasks.workflow_transition(
                actor,
                row.organization_id,
                row.workspace_id,
                self.root_submission(row.organization_id, row.workspace_id, row.submission_id),
                state,
            )

    def create_revision(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
        key: UUID,
        reason: str,
    ) -> Submission:
        row = self.access(actor, org, workspace, identifier, True)
        user = self.workflows.forms.authorization.user(actor, org)
        if row.owner_id != user.id or row.state not in {
            "returned",
            "rejected",
            "approved",
            "closed",
        }:
            raise ServiceError(403, "workflow_revision_owner_required")
        workflow, _ = self.definition(actor, row)
        self.workflows.forms.require(
            actor, org, workspace, workflow.project_id, "submission.create", True
        )
        root = self.root_submission(org, workspace, row.submission_id)
        existing = self.store.revision_by_source(org, workspace, row.id)
        if existing:
            if existing.idempotency_key != key or existing.reason != reason:
                raise ServiceError(409, "workflow_revision_already_created")
            return self.submissions.public(
                actor, self.submissions.access(actor, org, workspace, existing.submission_id)
            )
        if self.tasks:
            self.tasks.validate_revision_write(actor, org, workspace, root)
        if row.revision != expected:
            raise ServiceError(409, "stale_revision")
        source = self.submissions.snapshot(org, workspace, row.submission_id)
        draft = self.submissions.create_revision(actor, source, reason)
        revision = WorkflowRevision(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            source_instance_id=row.id,
            root_submission_id=root,
            submission_id=draft.id,
            owner_id=user.id,
            kind="amendment" if row.state in {"approved", "closed"} else "correction",
            reason=reason,
            idempotency_key=key,
            created_at=datetime.now(UTC),
        )
        self.store.add_revision(revision)
        self.workflows.event(
            actor, workflow, revision.id, "workflow.revision.created", row.workflow_number, reason
        )
        return self.submissions.public(actor, draft)

    def definition(
        self, actor: RequestContext, row: WorkflowInstance
    ) -> tuple[Workflow, WorkflowVersion]:
        workflow, version = self.workflows.version(
            actor, row.organization_id, row.workspace_id, row.workflow_id, row.workflow_number
        )
        if version.id != row.workflow_version_id:
            raise ServiceError(409, "workflow_version_mismatch")
        return workflow, version

    def authorized_step(
        self, actor: RequestContext, row: WorkflowInstance, step: WorkflowStep | AssignedStep
    ) -> bool:
        workflow, version = self.definition(actor, row)
        user = self.workflows.forms.authorization.user(actor, row.organization_id)
        node = next(item for item in version.definition.nodes if item.key == step.node_key)
        assigned = (
            user.id in step.recipient_ids
            if isinstance(step, WorkflowStep)
            else user.id == step.recipient_id
        )
        if not assigned or (node.kind == "approval" and user.id == row.owner_id):
            return False
        if not self.workflows.assignments.eligible(actor, workflow, user, node.kind == "approval"):
            return False
        submission = self.submissions.snapshot(
            row.organization_id, row.workspace_id, row.submission_id
        )
        return any(
            self.workflows.assignments.matches(actor, workflow, user, target, submission.values)
            for target in node.assignments
        )

    def access(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        lock: bool = False,
    ) -> WorkflowInstance:
        row = self.store.instance(org, workspace, identifier)
        if row is None:
            raise ServiceError(404, "not_found")
        workflow, _ = self.definition(actor, row)
        user = self.workflows.forms.authorization.user(actor, org)
        permissions = self.workflows.forms.permissions(actor, org, workspace, workflow.project_id)
        if lock:
            locked = self.store.instance(org, workspace, identifier, True)
            if locked is None:
                raise ServiceError(404, "not_found")
            row = locked
        if (
            row.owner_id != user.id
            and "workflow.manage" not in permissions
            and not any(
                self.authorized_step(actor, row, step)
                for step in self.store.participant_steps(org, workspace, row.id, user.id)
            )
        ):
            raise ServiceError(403, "workflow_private")
        return row

    def can_read(self, actor: RequestContext, submission: Submission) -> bool:
        row = self.store.by_submission(
            submission.organization_id, submission.workspace_id, submission.id
        )
        if not row:
            return False
        try:
            user = self.workflows.forms.authorization.user(actor, row.organization_id)
            return any(
                self.authorized_step(actor, row, step)
                for step in self.store.participant_steps(
                    row.organization_id, row.workspace_id, row.id, user.id
                )
            )
        except ServiceError:
            return False

    def available_actions(
        self, actor: RequestContext, row: WorkflowInstance
    ) -> list[Literal["review", "approve", "return", "reject"]]:
        if row.state != "active":
            return []
        step = self.store.current_step(
            row.organization_id, row.workspace_id, row.id, row.current_node
        )
        if not step or not self.authorized_step(actor, row, step):
            return []
        _, version = self.definition(actor, row)
        node = next(node for node in version.definition.nodes if node.key == step.node_key)
        assert node.policy
        user = self.workflows.forms.authorization.user(actor, row.organization_id)
        votes = frozenset(
            action.actor_id
            for action in self.store.actions_for_step(
                row.organization_id, row.workspace_id, row.id, step.id
            )
            if action.step_id == step.id
        )
        try:
            require_next_approver(node.policy.mode, tuple(step.recipient_ids), votes, user.id)
        except ValueError:
            return []
        output: list[Literal["review", "approve", "return", "reject"]] = ["reject"]
        if node.return_to:
            output.append("return")
        try:
            require_next_approver(node.policy.mode, tuple(step.recipient_ids), votes, user.id)
            output.insert(0, "approve" if node.kind == "approval" else "review")
        except ValueError:
            pass
        return output

    def submitted(self, actor: RequestContext, submission: Submission) -> None:
        org, workspace = submission.organization_id, submission.workspace_id
        if self.store.by_submission(org, workspace, submission.id):
            return
        revision = self.store.revision_by_submission(org, workspace, submission.id)
        if revision:
            source = self.store.instance(org, workspace, revision.source_instance_id)
            if source is None:
                raise ServiceError(409, "workflow_revision_source_missing")
            workflow, version = self.definition(actor, source)
        else:
            candidate = self.workflows.store.active_for_form(
                org, workspace, submission.form_version_id
            )
            if candidate is None:
                return
            version = candidate
            workflow = self.workflows.get(actor, org, workspace, version.workflow_id, lock=True)
            live = self.workflows.store.version(org, workspace, workflow.id, version.number)
            if live is None or live.state != "active" or workflow.active_number != version.number:
                raise ServiceError(409, "workflow_binding_changed")
            version = live
        start = next(node.key for node in version.definition.nodes if node.kind == "start")
        row = WorkflowInstance(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            workflow_number=version.number,
            submission_id=submission.id,
            owner_id=submission.owner_id,
            current_node=start,
            created_at=datetime.now(UTC),
        )
        self.store.add_instance(row)
        self.workflows.event(actor, workflow, row.id, "workflow.instance.started", version.number)
        self.advance(actor, row, version, submission, start)

    def next_node(self, version: WorkflowVersion, key: str, outcome: str = "continue") -> str:
        return next(
            edge.target
            for edge in version.definition.transitions
            if edge.source == key and edge.outcome == outcome
        )

    def advance(
        self,
        actor: RequestContext,
        row: WorkflowInstance,
        version: WorkflowVersion,
        submission: Submission,
        key: str,
    ) -> WorkflowInstance:
        workflow = self.workflows.get(actor, row.organization_id, row.workspace_id, row.workflow_id)
        step_count = self.store.step_count(row.organization_id, row.workspace_id, row.id)
        if step_count > 1000:
            raise ServiceError(422, "workflow_visit_limit")
        for _ in range(100):
            node = next(node for node in version.definition.nodes if node.key == key)
            if node.kind in {"review", "approval"}:
                if step_count >= 1000:
                    raise ServiceError(422, "workflow_visit_limit")
                recipients = self.workflows.assignments.resolve(
                    actor, workflow, node.assignments, node.kind == "approval", submission.values
                )
                if node.kind == "approval":
                    recipients = list(eligible_approvers(tuple(recipients), submission.owner_id))
                if not recipients or (
                    node.policy and node.policy.quorum and node.policy.quorum > len(recipients)
                ):
                    raise ServiceError(422, "workflow_independent_assignment_unavailable")
                step = WorkflowStep(
                    id=uuid7(),
                    organization_id=row.organization_id,
                    workspace_id=row.workspace_id,
                    instance_id=row.id,
                    node_key=key,
                    number=step_count + 1,
                    recipient_ids=recipients,
                    created_at=datetime.now(UTC),
                )
                self.store.add_step(step)
                self.workflows.event(
                    actor, workflow, step.id, "workflow.step.assigned", step.number
                )
                changed = row.model_copy(update={"current_node": key, "revision": row.revision + 1})
                break
            if node.kind == "end":
                approval_keys = {
                    item.key for item in version.definition.nodes if item.kind == "approval"
                }
                approved = self.store.completed_approval(
                    row.organization_id, row.workspace_id, row.id, approval_keys
                )
                changed = row.model_copy(
                    update={
                        "current_node": key,
                        "state": "approved" if approved else "closed",
                        "revision": row.revision + 1,
                    }
                )
                self.workflows.event(
                    actor, workflow, row.id, "workflow.instance." + changed.state, version.number
                )
                break
            if node.kind == "notify":
                recipients = self.workflows.assignments.resolve(
                    actor, workflow, node.assignments, False, submission.values, notification=True
                )
                if not recipients:
                    raise ServiceError(422, "workflow_notification_assignment_unavailable")
                notification = WorkflowNotification(
                    id=uuid7(),
                    organization_id=row.organization_id,
                    workspace_id=row.workspace_id,
                    instance_id=row.id,
                    node_key=key,
                    visit=step_count + 1,
                    recipient_ids=recipients,
                    created_at=datetime.now(UTC),
                )
                self.store.notify(notification)
                self.workflows.event(
                    actor, workflow, notification.id, "workflow.notification.requested"
                )
            outcome = "continue"
            if node.kind == "decision":
                assert node.condition
                outcome = (
                    "true" if condition_matches(node.condition, submission.values) else "false"
                )
            key = self.next_node(version, key, outcome)
        else:
            raise ServiceError(422, "workflow_transition_limit")
        if not self.store.save_instance(changed, row.revision):
            raise ServiceError(409, "stale_revision")
        self.sync_tasks(actor, changed)
        return changed

    def act(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
        key: UUID,
        kind: Literal["review", "approve", "return", "reject"],
        reason: str,
    ) -> WorkflowInstance:
        row = self.access(actor, org, workspace, identifier, True)
        workflow, version = self.definition(actor, row)
        self.workflows.forms.require(
            actor, org, workspace, workflow.project_id, "workflow.act", True
        )
        user = self.workflows.forms.authorization.user(actor, org)
        replay = self.store.action_by_key(org, key)
        if replay:
            steps = self.store.participant_steps(org, workspace, row.id, user.id)
            replay_step = next((step for step in steps if step.id == replay.step_id), None)
            if (
                replay.instance_id != row.id
                or replay.actor_id != user.id
                or replay.kind != kind
                or replay.reason != reason
            ):
                raise ServiceError(409, "workflow_idempotency_conflict")
            if replay_step is None or not self.authorized_step(actor, row, replay_step):
                raise ServiceError(403, "workflow_assignment_revoked")
            return row
        step = self.store.current_step(org, workspace, row.id, row.current_node)
        if row.state != "active" or row.revision != expected or step is None:
            raise ServiceError(409, "workflow_action_conflict")
        if not self.authorized_step(actor, row, step):
            raise ServiceError(403, "workflow_not_assigned")
        node = next(node for node in version.definition.nodes if node.key == step.node_key)
        assert node.policy
        if kind in {"review", "approve"} and kind != (
            "approve" if node.kind == "approval" else "review"
        ):
            raise ServiceError(422, "workflow_wrong_action_kind")
        if kind == "return" and node.return_to is None:
            raise ServiceError(422, "workflow_return_not_configured")
        actions = self.store.actions_for_step(org, workspace, row.id, step.id)
        votes = frozenset(
            action.actor_id
            for action in actions
            if action.step_id == step.id and action.kind in {"review", "approve"}
        )
        try:
            require_next_approver(node.policy.mode, tuple(step.recipient_ids), votes, user.id)
        except ValueError as error:
            raise ServiceError(409, str(error)) from error
        action = WorkflowAction(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            instance_id=row.id,
            step_id=step.id,
            actor_id=user.id,
            kind=kind,
            reason=reason,
            idempotency_key=key,
            occurred_at=datetime.now(UTC),
        )
        self.store.add_action(action)
        self.workflows.event(
            actor, workflow, action.id, "workflow.action." + kind, version.number, reason
        )
        if kind in {"return", "reject"}:
            self.store.save_step(
                step.model_copy(update={"state": "returned" if kind == "return" else "rejected"})
            )
            if node.return_to and node.return_to != "submitter":
                submission = self.submissions.snapshot(org, workspace, row.submission_id)
                assert node.return_to
                return self.advance(actor, row, version, submission, node.return_to)
            changed = row.model_copy(
                update={
                    "state": "returned" if node.return_to else "rejected",
                    "revision": row.revision + 1,
                }
            )
        elif approval_complete(
            node.policy.mode, tuple(step.recipient_ids), votes | {user.id}, node.policy.quorum
        ):
            self.store.save_step(step.model_copy(update={"state": "completed"}))
            submission = self.submissions.snapshot(org, workspace, row.submission_id)
            return self.advance(actor, row, version, submission, self.next_node(version, node.key))
        else:
            changed = row.model_copy(update={"revision": row.revision + 1})
        if not self.store.save_instance(changed, row.revision):
            raise ServiceError(409, "stale_revision")
        self.sync_tasks(actor, changed)
        return changed


class SubmissionLifecycle:
    def __init__(self, tasks: TaskService, workflows: WorkflowRuntime) -> None:
        self.tasks, self.workflows = tasks, workflows

    def validate_write(self, actor: RequestContext, submission: Submission) -> None:
        self.tasks.validate_write(actor, submission)
        revision = self.workflows.store.revision_by_submission(
            submission.organization_id, submission.workspace_id, submission.id
        )
        if revision:
            self.tasks.validate_revision_write(
                actor,
                submission.organization_id,
                submission.workspace_id,
                revision.root_submission_id,
            )

    def submitted(self, actor: RequestContext, submission: Submission) -> None:
        self.tasks.submitted(actor, submission)
        self.workflows.submitted(actor, submission)


class WorkflowTasks(Protocol):
    def workflow_transition(
        self, actor: RequestContext, org: UUID, workspace: UUID, root: UUID, state: str
    ) -> None: ...
    def validate_revision_write(
        self, actor: RequestContext, org: UUID, workspace: UUID, root: UUID
    ) -> None: ...
