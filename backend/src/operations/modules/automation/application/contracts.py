from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from operations.contracts import Command
from operations.modules.automation.application.events import Delivery, EventType, OperationalEvent
from operations.modules.forms.application.contracts import Expression
from operations.modules.master_data.application.contracts import RecordValues
from operations.modules.scheduling.application.contracts import Assignment


def default_channels() -> list[Literal["in_app", "email"]]:
    return ["in_app"]


class NotifyAction(Command):
    kind: Literal["notify"]
    recipients: list[UUID] = Field(min_length=1, max_length=100)
    channels: list[Literal["in_app", "email"]] = Field(
        default_factory=default_channels, min_length=1, max_length=2
    )
    topic: Literal["work_assigned", "review_requested", "rule_notice"] = "rule_notice"


class TaskAction(Command):
    kind: Literal["create_task", "create_form_task"]
    name: str = Field(min_length=1, max_length=120)
    form_id: UUID | None = None
    form_number: int | None = Field(default=None, ge=1)
    assignments: list[Assignment] = Field(min_length=1, max_length=20)
    due_seconds: int = Field(default=86400, ge=60, le=2592000)

    @model_validator(mode="after")
    def coherent(self) -> TaskAction:
        if (self.form_id is None) != (self.form_number is None) or (
            self.kind == "create_form_task" and self.form_id is None
        ):
            raise ValueError("automation_task_form_pin_required")
        return self


class WorkflowAction(Command):
    kind: Literal["start_workflow"]
    workflow_id: UUID


class MetadataAction(Command):
    kind: Literal["set_metadata"]
    description: str = Field(max_length=2000)


class RecordAction(Command):
    kind: Literal["create_related_record"]
    type_id: UUID
    name: str = Field(min_length=1, max_length=200)
    values: RecordValues


class WebhookAction(Command):
    kind: Literal["call_webhook"]
    endpoint_id: UUID


class TagAction(Command):
    kind: Literal["append_tag", "append_flag"]
    value: str = Field(min_length=1, max_length=60, pattern=r"^[a-zA-Z0-9_.:-]+$")


type AutomationAction = Annotated[
    NotifyAction
    | TaskAction
    | WorkflowAction
    | MetadataAction
    | RecordAction
    | WebhookAction
    | TagAction,
    Field(discriminator="kind"),
]


class RuleDefinition(Command):
    trigger: EventType
    form_id: UUID | None = None
    form_number: int | None = Field(default=None, ge=1)
    condition: Expression | None = None
    actions: list[AutomationAction] = Field(min_length=1, max_length=20)
    timer_start: datetime | None = None
    timer_seconds: int | None = Field(default=None, ge=60, le=2592000)

    @model_validator(mode="after")
    def coherent(self) -> RuleDefinition:
        if (self.form_id is None) != (self.form_number is None):
            raise ValueError("automation_form_pin_required")
        if self.trigger == "scheduled.timer":
            if (
                self.timer_start is None
                or self.timer_start.utcoffset() is None
                or self.timer_seconds is None
            ):
                raise ValueError("automation_timer_requires_aware_start_and_interval")
        elif self.timer_start is not None or self.timer_seconds is not None:
            raise ValueError("automation_timer_only_for_timer_trigger")
        return self


class Rule(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    active_number: int | None = None
    revision: int = Field(default=1, ge=1)


class RuleVersion(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    rule_id: UUID
    number: int = Field(ge=1)
    definition: RuleDefinition
    revision: int = Field(default=1, ge=1)
    state: Literal["draft", "active", "retired"] = "draft"
    activator_id: UUID | None = None
    activated_at: datetime | None = None
    content_sha256: str | None = None


class Run(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    rule_version_id: UUID
    event_id: UUID
    delegator_id: UUID
    trigger_actor_id: UUID | None = None
    correlation_id: UUID
    state: Literal["pending", "completed", "skipped", "retry", "dead_letter"] = "pending"
    attempts: int = Field(default=0, ge=0, le=20)
    next_at: datetime
    created_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None


class RunAttempt(Command):
    id: UUID
    organization_id: UUID
    run_id: UUID
    number: int = Field(ge=1, le=20)
    started_at: datetime
    finished_at: datetime
    outcome: Literal["completed", "skipped", "retry", "dead_letter"]
    error_code: str | None = None


class Receipt(Command):
    id: UUID
    organization_id: UUID
    run_id: UUID
    position: int = Field(ge=0, le=19)
    kind: str
    target_id: UUID | None = None
    created_at: datetime


class AutomationStore(Protocol):
    def append(self, event: OperationalEvent) -> None: ...
    def event(self, org: UUID, identifier: UUID) -> OperationalEvent | None: ...
    def create_rule(self, row: Rule) -> None: ...
    def rule(
        self, org: UUID, workspace: UUID, identifier: UUID, lock: bool = False
    ) -> Rule | None: ...
    def rules(
        self, org: UUID, workspace: UUID, project: UUID | None, after: UUID | None
    ) -> list[Rule]: ...
    def save_rule(self, row: Rule, expected: int) -> bool: ...
    def add_version(self, row: RuleVersion) -> None: ...
    def version(
        self, org: UUID, workspace: UUID, rule: UUID, number: int, lock: bool = False
    ) -> RuleVersion | None: ...
    def version_by_id(self, org: UUID, identifier: UUID) -> RuleVersion | None: ...
    def versions(
        self, org: UUID, workspace: UUID, rule: UUID, after: UUID | None
    ) -> list[RuleVersion]: ...
    def save_version(self, row: RuleVersion, expected: int) -> bool: ...
    def matching(self, event: OperationalEvent) -> list[RuleVersion]: ...
    def add_delivery(self, row: Delivery) -> None: ...
    def delivery(self, org: UUID, identifier: UUID, lock: bool = False) -> Delivery | None: ...
    def due_deliveries(self, org: UUID, now: datetime) -> list[Delivery]: ...
    def save_delivery(self, row: Delivery) -> None: ...
    def add_run(self, row: Run) -> None: ...
    def run(self, org: UUID, identifier: UUID, lock: bool = False) -> Run | None: ...
    def event_runs(self, org: UUID, event: UUID) -> list[Run]: ...
    def runs(
        self, org: UUID, workspace: UUID, version: UUID | None, after: UUID | None
    ) -> list[Run]: ...
    def save_run(self, row: Run) -> None: ...
    def add_attempt(self, row: RunAttempt) -> None: ...
    def attempts(self, org: UUID, run: UUID) -> list[RunAttempt]: ...
    def add_receipt(self, row: Receipt) -> None: ...
    def receipts(self, org: UUID, run: UUID) -> list[Receipt]: ...
