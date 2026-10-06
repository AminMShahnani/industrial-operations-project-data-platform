from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.actions import ApplicationActions
from operations.modules.automation.application.contracts import (
    MetadataAction,
    RecordAction,
    Rule,
    RuleDefinition,
    Run,
    TaskAction,
    WorkflowAction,
)
from operations.modules.automation.application.events import (
    DeliveryMessage,
    EventContext,
    OperationalEvent,
)
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import EventRow
from operations.modules.forms.application.contracts import Expression, FormValues
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.identity.infrastructure.persistence import UserRow
from operations.modules.master_data.application.contracts import RecordValues
from operations.modules.master_data.infrastructure.persistence import DataRecordRow
from operations.modules.tasks.infrastructure.persistence import TaskRow
from operations.worker import process_automation
from sqlalchemy import func, select, update
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project, type_definition
from test_phase3_api import draft, publish, setup
from test_phase5_api import activate as activate_workflow
from test_phase5_api import create_workflow, definition, reviewer

pytestmark = pytest.mark.integration


def context(api: Api, org: UUID) -> tuple[RequestContext, UUID]:
    user = api.session.scalar(select(UserRow).where(UserRow.organization_id == org))
    assert user
    return RequestContext(Principal(user.issuer, user.subject), uuid7(), uuid7()), user.id


def activate(
    api: Api,
    actor: RequestContext,
    org: UUID,
    workspace: UUID,
    project_id: UUID | None,
    definition: RuleDefinition,
) -> Rule:
    service = compose(api.session).automation
    row = service.create(actor, org, workspace, project_id, "Authorized action", definition)
    preview = service.activate(actor, org, workspace, row.id, 1, 1, True, None)
    service.activate(actor, org, workspace, row.id, 1, 1, False, preview.content_sha256)
    return row


def test_project_metadata_action_real_consumer_duplicate_and_audit(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, _ = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="project.phase.changed",
            actions=[MetadataAction(kind="set_metadata", description="Activated phase notice")],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin work")
    source = api.session.scalar(
        select(AuditRow).where(
            AuditRow.type == "project.transitioned", AuditRow.aggregate_id == identifier
        )
    )
    assert source
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    result = process_automation(api.session, message)
    assert result.state == "completed"
    assert process_automation(api.session, message) == result
    row = services.projects.require_access(actor, org, workspace, identifier, "project.read")
    assert row.context.description == "Activated phase notice" and row.version == 3
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.type == "project.updated", AuditRow.aggregate_id == identifier
        )
    )
    assert audit and audit.payload["authorization_kind"] == "delegated_automation"
    assert audit.payload["run_id"]
    with pytest.raises(ServiceError, match="outbox_delivery_not_found"):
        process_automation(api.session, message.model_copy(update={"organization_id": uuid7()}))


def test_form_task_pins_recipients_and_caused_events_once(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    actor, user = context(api, org)
    action = TaskAction.model_validate(
        {
            "kind": "create_form_task",
            "name": "Derived form",
            "form_id": form,
            "form_number": 1,
            "assignments": [{"kind": "user", "target_id": user}],
            "due_seconds": 60,
        }
    )
    rule = activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="submission.submitted", form_id=UUID(form), form_number=1, actions=[action]
        ),
    )
    submission = draft(api, route, form)
    service = compose(api.session).submissions
    saved = service.save(
        actor, org, workspace, UUID(submission), FormValues(fields={"quantity": 2}), 1
    )
    service.submit(
        actor,
        org,
        workspace,
        UUID(submission),
        saved.revision,
        uuid7(),
        "submit derived task source",
    )
    source = api.session.scalar(
        select(AuditRow).where(
            AuditRow.type == "submission.submitted", AuditRow.aggregate_id == UUID(submission)
        )
    )
    assert source
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    process_automation(api.session, message)
    tasks = api.session.scalars(select(TaskRow).where(TaskRow.organization_id == org)).all()
    assert len(tasks) == 1 and tasks[0].form_number == 1
    assert tasks[0].due_at == source.occurred_at + timedelta(seconds=60)
    runs = compose(api.session).automation.store.event_runs(org, source.id)
    receipt = compose(api.session).automation.store.receipts(org, runs[0].id)[0]
    assert receipt.target_id == tasks[0].schedule_id
    task_event = api.session.scalar(select(AuditRow).where(AuditRow.type == "task.created"))
    assert task_event
    caused = compose(api.session).automation.store.event(org, task_event.id)
    assert caused and caused.causation_id == source.id
    version = compose(api.session).automation.store.version(org, workspace, rule.id, 1)
    assert version and caused.causation_path == [version.id]


def test_revoked_authority_retains_dead_letter_without_effects(api: Api) -> None:
    org, workspace, _, _ = setup(api)
    actor, user = context(api, org)
    type_id = UUID(type_definition(api, org, workspace))
    action = RecordAction(
        kind="create_related_record",
        type_id=type_id,
        name="Derived record",
        values=RecordValues(fields={"latitude": "1.00"}),
    )
    row = activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(trigger="integration.event", actions=[action, action]),
    )
    service = compose(api.session).automation
    source = OperationalEvent(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        type="integration.event",
        occurred_at=datetime.now(UTC),
        actor_id=user,
        correlation_id=actor.correlation_id,
        aggregate_type="integration",
        aggregate_id=uuid7(),
    )
    service.capture(source)
    # Live target access is revoked after capture; effects must not be produced.
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == user)
        .values(revoked=True)
    )
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    assert process_automation(api.session, message).state == "dead_letter"
    run = service.store.event_runs(org, source.id)[0]
    assert run.state == "dead_letter" and service.store.receipts(org, run.id) == []
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(DataRecordRow)
            .where(DataRecordRow.organization_id == org)
        )
        == 0
    )
    assert service.store.version(org, workspace, row.id, 1)


def test_second_action_failure_rolls_back_then_retry_completes_once(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    type_id = UUID(type_definition(api, org, workspace))
    action = RecordAction(
        kind="create_related_record",
        type_id=type_id,
        name="Derived",
        values=RecordValues(fields={"latitude": "1.00"}),
    )
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(trigger="integration.event", actions=[action, action]),
    )
    service = compose(api.session).automation
    source = OperationalEvent(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        type="integration.event",
        occurred_at=datetime.now(UTC),
        actor_id=user,
        correlation_id=actor.correlation_id,
        aggregate_type="integration",
        aggregate_id=uuid7(),
    )
    service.capture(source)
    original = ApplicationActions.execute

    def fail_second(
        self: ApplicationActions,
        context: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: MetadataAction | RecordAction | TaskAction,
    ) -> UUID | None:
        if position == 1:
            raise ServiceError(503, "fixture_transient_dependency")
        return original(self, context, rule, event, run, position, action)

    monkeypatch.setattr(ApplicationActions, "execute", fail_second)
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    assert process_automation(api.session, message).state == "retry"
    run = service.store.event_runs(org, source.id)[0]
    assert run.state == "retry" and service.store.receipts(org, run.id) == []
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(DataRecordRow)
            .where(DataRecordRow.organization_id == org)
        )
        == 0
    )
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(EventRow)
            .where(EventRow.organization_id == org, EventRow.type == "master_data.changed")
        )
        == 0
    )
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(AuditRow.organization_id == org, AuditRow.type == "master_data.record.created")
        )
        == 0
    )
    # A duplicate message before next_at produces no extra attempt or effect.
    process_automation(api.session, message)
    assert len(service.store.attempts(org, run.id)) == 1
    monkeypatch.setattr(ApplicationActions, "execute", original)
    due = datetime.now(UTC) - timedelta(seconds=1)
    service.store.save_run(run.model_copy(update={"next_at": due}))
    delivery = service.store.delivery(org, message.delivery_id)
    assert delivery
    service.store.save_delivery(delivery.model_copy(update={"next_at": due}))
    assert process_automation(api.session, message).state == "completed"
    process_automation(api.session, message)
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(DataRecordRow)
            .where(DataRecordRow.organization_id == org)
        )
        == 2
    )
    assert len(service.store.receipts(org, run.id)) == 2
    assert [item.outcome for item in service.store.attempts(org, run.id)] == ["retry", "completed"]


def test_condition_false_skips_real_action_and_unknown_lookup_fails(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, _ = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="project.phase.changed",
            condition=Expression(op="literal", value=False),
            actions=[MetadataAction(kind="set_metadata", description="must not apply")],
        ),
    )
    services = compose(api.session)
    services.projects.transition(actor, org, workspace, identifier, "active", 1, "begin")
    source = api.session.scalar(select(AuditRow).where(AuditRow.type == "project.transitioned"))
    assert source
    process_automation(
        api.session,
        DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation")),
    )
    assert services.automation.store.event_runs(org, source.id)[0].state == "skipped"
    assert (
        services.projects.require_access(
            actor, org, workspace, identifier, "project.read"
        ).context.description
        == ""
    )
    with pytest.raises(ServiceError):
        services.automation.create(
            actor,
            org,
            workspace,
            identifier,
            "Invalid lookup",
            RuleDefinition(
                trigger="project.phase.changed",
                condition=Expression(op="field", key="unpermitted_lookup"),
                actions=[MetadataAction(kind="set_metadata", description="")],
            ),
        )


def test_workflow_action_preserves_exact_binding_and_independent_approval(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    voter = reviewer(api, org, workspace)
    workflow = create_workflow(api, route, definition(form, [voter]))
    activate_workflow(api, route, workflow)
    actor, _ = context(api, org)
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="submission.submitted",
            form_id=UUID(form),
            form_number=1,
            actions=[
                WorkflowAction(kind="start_workflow", workflow_id=UUID(workflow), workflow_number=1)
            ],
        ),
    )
    service = compose(api.session)
    submission = UUID(draft(api, route, form))
    saved = service.submissions.save(
        actor, org, workspace, submission, FormValues(fields={"quantity": 2}), 1
    )
    service.submissions.submit(actor, org, workspace, submission, saved.revision, uuid7(), "submit")
    instance = service.workflow_runtime.store.by_submission(org, workspace, submission)
    assert instance and instance.state == "active"
    source = api.session.scalar(
        select(AuditRow).where(
            AuditRow.type == "submission.submitted", AuditRow.aggregate_id == submission
        )
    )
    assert source
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    assert service.workflow_runtime.store.by_submission(org, workspace, submission) == instance
    assert service.workflow_runtime.available_actions(actor, instance) == []


def test_action_target_scope_and_private_source_are_enforced(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    actor, _ = context(api, org)
    other_workspace = api.workspace(org)
    foreign_type = UUID(type_definition(api, org, other_workspace))
    with pytest.raises(ServiceError, match="automation_record_scope_mismatch"):
        activate(
            api,
            actor,
            org,
            workspace,
            None,
            RuleDefinition(
                trigger="integration.event",
                actions=[
                    RecordAction(
                        kind="create_related_record",
                        type_id=foreign_type,
                        name="Wrong scope",
                        values=RecordValues(fields={"latitude": "1"}),
                    )
                ],
            ),
        )
    token = api.invitation(org, workspace, "Contributor")
    api.accept(org, token)
    contributor_draft = UUID(draft(api, route, form, "invitee"))
    services = compose(api.session)
    event = OperationalEvent(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        type="submission.created",
        occurred_at=datetime.now(UTC),
        correlation_id=uuid7(),
        aggregate_type="submission",
        aggregate_id=contributor_draft,
        payload=EventContext(form_id=UUID(form), form_number=1, submission_id=contributor_draft),
    )
    with pytest.raises(ServiceError, match="submission_private"):
        services.automation.actions.values(actor, event)
