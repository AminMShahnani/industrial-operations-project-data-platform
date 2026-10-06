from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.forms.application.contracts import Expression
from operations.modules.workflows.domain.graph import (
    ApprovalMode,
    Edge,
    Node,
    NodeKind,
    validate_graph,
)


class Assignment(Command):
    kind: Literal[
        "user", "project_role", "department_role", "team", "submission_field", "manager_of"
    ]
    target_id: UUID | None = None
    role: str | None = Field(default=None, min_length=1, max_length=60)
    field_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,59}$")

    @model_validator(mode="after")
    def coherent(self) -> Assignment:
        required = {
            "user": (True, False, False),
            "project_role": (False, True, False),
            "department_role": (True, True, False),
            "team": (True, False, False),
            "submission_field": (False, False, True),
            "manager_of": (False, False, True),
        }[self.kind]
        if required != (
            self.target_id is not None,
            self.role is not None,
            self.field_key is not None,
        ):
            raise ValueError("invalid_workflow_assignment")
        return self


class ApprovalPolicy(Command):
    mode: ApprovalMode = "one"
    quorum: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def coherent(self) -> ApprovalPolicy:
        if (self.mode == "quorum") != (self.quorum is not None):
            raise ValueError("quorum_requires_quorum_policy")
        return self


class WorkflowNode(Command):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    name: str = Field(min_length=1, max_length=120)
    kind: NodeKind
    assignments: list[Assignment] = Field(default_factory=list, max_length=20)
    policy: ApprovalPolicy | None = None
    condition: Expression | None = None
    return_to: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def coherent(self) -> WorkflowNode:
        if (self.kind in {"review", "approval", "notify"}) != bool(self.assignments):
            raise ValueError("workflow_node_assignment_required_or_inapplicable")
        if (self.kind in {"review", "approval"}) != (self.policy is not None):
            raise ValueError("workflow_node_policy_required_or_inapplicable")
        if (self.kind == "decision") != (self.condition is not None):
            raise ValueError("workflow_decision_condition_required_or_inapplicable")
        return self


class WorkflowTransition(Command):
    source: str = Field(max_length=60)
    target: str = Field(max_length=60)
    outcome: Literal["continue", "true", "false"] = "continue"


class WorkflowDefinition(Command):
    form_id: UUID
    form_number: int = Field(ge=1)
    nodes: list[WorkflowNode] = Field(min_length=2, max_length=100)
    transitions: list[WorkflowTransition] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def graph(self) -> WorkflowDefinition:
        validate_graph(
            tuple(Node(node.key, node.kind, node.return_to) for node in self.nodes),
            tuple(Edge(edge.source, edge.target, edge.outcome) for edge in self.transitions),
        )
        return self


class Workflow(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    active_number: int | None = Field(default=None, ge=1)
    revision: int = Field(default=1, ge=1)


class WorkflowVersion(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    workflow_id: UUID
    number: int = Field(ge=1)
    definition: WorkflowDefinition
    state: Literal["draft", "active", "retired"] = "draft"
    revision: int = Field(default=1, ge=1)
    form_version_id: UUID | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    activated_at: datetime | None = None


class WorkflowInstance(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_number: int = Field(ge=1)
    submission_id: UUID
    owner_id: UUID
    state: Literal["active", "returned", "approved", "closed", "rejected"] = "active"
    current_node: str = Field(max_length=60)
    revision: int = Field(default=1, ge=1)
    created_at: datetime


class WorkflowStep(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    instance_id: UUID
    node_key: str = Field(max_length=60)
    number: int = Field(ge=1)
    recipient_ids: list[UUID] = Field(min_length=1, max_length=1000)
    state: Literal["open", "completed", "returned", "rejected"] = "open"
    created_at: datetime


class WorkflowAction(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    instance_id: UUID
    step_id: UUID
    actor_id: UUID
    kind: Literal["review", "approve", "return", "reject"]
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: UUID
    occurred_at: datetime


class WorkflowStore(Protocol):
    def create(self, workflow: Workflow) -> None: ...
    def get(self, org: UUID, workspace: UUID, identifier: UUID) -> Workflow | None: ...
    def list_workflows(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Workflow]: ...
    def save(self, workflow: Workflow, expected: int) -> bool: ...
    def add_version(self, version: WorkflowVersion) -> None: ...
    def version(
        self, org: UUID, workspace: UUID, identifier: UUID, number: int
    ) -> WorkflowVersion | None: ...
    def versions(
        self, org: UUID, workspace: UUID, identifier: UUID, after: UUID | None
    ) -> list[WorkflowVersion]: ...
    def save_version(self, version: WorkflowVersion, expected: int) -> bool: ...
