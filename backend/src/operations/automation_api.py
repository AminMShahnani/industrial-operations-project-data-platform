from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from operations.api import Context, ServiceDependency
from operations.contracts import Command
from operations.modules.automation.application.contracts import (
    Rule,
    RuleDefinition,
    RuleVersion,
    Run,
    RunHistory,
    RunReplayReview,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/workspaces/{workspace_id}",
    tags=["automation"],
)


class AutomationCreate(Command):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    project_id: UUID | None = None
    definition: RuleDefinition


class AutomationSave(Command):
    expected_revision: int = Field(ge=1)
    definition: RuleDefinition


class AutomationClone(Command):
    source_number: int = Field(ge=1)
    number: int = Field(ge=1)


class AutomationActivation(Command):
    expected_revision: int = Field(ge=1)
    dry_run: bool = True
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class AutomationRetire(Command):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class AutomationReplay(Command):
    dry_run: bool = True
    review_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, min_length=1, max_length=500, pattern=r"\S")


class AutomationRulePage(Command):
    items: list[Rule]
    next_cursor: UUID | None = None


class AutomationVersionPage(Command):
    items: list[RuleVersion]
    next_cursor: UUID | None = None


class AutomationRunPage(Command):
    items: list[Run]
    next_cursor: UUID | None = None


@router.post("/automation-rules", response_model=Rule, status_code=201)
def create(
    organization_id: UUID,
    workspace_id: UUID,
    command: AutomationCreate,
    actor: Context,
    services: ServiceDependency,
) -> Rule:
    return services.automation.create(
        actor, organization_id, workspace_id, command.project_id, command.name, command.definition
    )


@router.get("/automation-rules", response_model=AutomationRulePage)
def rules(
    organization_id: UUID,
    workspace_id: UUID,
    actor: Context,
    services: ServiceDependency,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
) -> AutomationRulePage:
    services.forms.require(actor, organization_id, workspace_id, project_id, "automation.manage")
    rows = services.automation.store.rules(organization_id, workspace_id, project_id, cursor)
    return AutomationRulePage(
        items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None
    )


@router.get("/automation-rules/{rule_id}", response_model=Rule)
def rule(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    actor: Context,
    services: ServiceDependency,
) -> Rule:
    return services.automation.inspect_rule(actor, organization_id, workspace_id, rule_id)


@router.get("/automation-rules/{rule_id}/versions", response_model=AutomationVersionPage)
def versions(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    actor: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> AutomationVersionPage:
    services.automation.inspect_rule(actor, organization_id, workspace_id, rule_id)
    rows = services.automation.store.versions(organization_id, workspace_id, rule_id, cursor)
    return AutomationVersionPage(
        items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None
    )


@router.get("/automation-rules/{rule_id}/versions/{number}", response_model=RuleVersion)
def version(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    number: int,
    actor: Context,
    services: ServiceDependency,
) -> RuleVersion:
    return services.automation.inspect_version(
        actor, organization_id, workspace_id, rule_id, number
    )


@router.post("/automation-rules/{rule_id}/versions", response_model=RuleVersion, status_code=201)
def clone(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    command: AutomationClone,
    actor: Context,
    services: ServiceDependency,
) -> RuleVersion:
    return services.automation.clone(
        actor, organization_id, workspace_id, rule_id, command.source_number, command.number
    )


@router.put("/automation-rules/{rule_id}/versions/{number}", response_model=RuleVersion)
def save(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    number: int,
    command: AutomationSave,
    actor: Context,
    services: ServiceDependency,
) -> RuleVersion:
    return services.automation.save(
        actor,
        organization_id,
        workspace_id,
        rule_id,
        number,
        command.expected_revision,
        command.definition,
    )


@router.post("/automation-rules/{rule_id}/versions/{number}/activate", response_model=RuleVersion)
def activate(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    number: int,
    command: AutomationActivation,
    actor: Context,
    services: ServiceDependency,
) -> RuleVersion:
    return services.automation.activate(
        actor,
        organization_id,
        workspace_id,
        rule_id,
        number,
        command.expected_revision,
        command.dry_run,
        command.expected_sha256,
    )


@router.post("/automation-rules/{rule_id}/retire", response_model=Rule)
def retire(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    command: AutomationRetire,
    actor: Context,
    services: ServiceDependency,
) -> Rule:
    return services.automation.retire(
        actor,
        organization_id,
        workspace_id,
        rule_id,
        command.expected_revision,
        command.reason.strip(),
    )


@router.get("/automation-rules/{rule_id}/versions/{number}/runs", response_model=AutomationRunPage)
def runs(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    number: int,
    actor: Context,
    services: ServiceDependency,
    cursor: UUID | None = None,
) -> AutomationRunPage:
    row = services.automation.inspect_version(actor, organization_id, workspace_id, rule_id, number)
    rows = services.automation.store.runs(organization_id, workspace_id, row.id, cursor)
    return AutomationRunPage(items=rows[:100], next_cursor=rows[99].id if len(rows) > 100 else None)


@router.get("/automation-rules/{rule_id}/runs/{run_id}", response_model=RunHistory)
def history(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    run_id: UUID,
    actor: Context,
    services: ServiceDependency,
) -> RunHistory:
    return services.automation.history(actor, organization_id, workspace_id, rule_id, run_id)


@router.post("/automation-rules/{rule_id}/runs/{run_id}/replay", response_model=RunReplayReview)
def replay(
    organization_id: UUID,
    workspace_id: UUID,
    rule_id: UUID,
    run_id: UUID,
    command: AutomationReplay,
    actor: Context,
    services: ServiceDependency,
) -> RunReplayReview:
    return services.automation.review_replay(
        actor,
        organization_id,
        workspace_id,
        rule_id,
        run_id,
        dry_run=command.dry_run,
        review_sha256=command.review_sha256,
        reason=command.reason,
    )
