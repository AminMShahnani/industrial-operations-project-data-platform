from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRepository, AuditRow
from operations.modules.automation.application.contracts import (
    AutomationAction,
    NotifyAction,
    Rule,
    RuleDefinition,
    Run,
)
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.automation.application.events import (
    DeliveryMessage,
    EventContext,
    OperationalEvent,
)
from operations.modules.automation.application.service import AutomationService
from operations.modules.automation.infrastructure.persistence import AutomationRepository, EventRow
from operations.modules.forms.application.contracts import FormValues
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.identity.infrastructure.persistence import UserRow
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import draft, publish, setup

pytestmark = pytest.mark.integration


class Actions:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int]] = []

    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None:
        pass

    def values(self, actor: RequestContext, event: OperationalEvent) -> FormValues:
        return FormValues(fields={"event_type": event.type})

    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID:
        self.calls.append((run.id, position))
        return run.id


def setup_service(api: Api) -> tuple[AutomationService, RequestContext, UUID, UUID, UUID, Actions]:
    org = api.organization()
    workspace = api.workspace(org)
    user = api.session.scalar(select(UserRow).where(UserRow.organization_id == org))
    assert user
    actor = RequestContext(Principal(user.issuer, user.subject), uuid7(), uuid7())
    audit = AuditedEventBus(AuditRepository(api.session, actor.principal))
    actions = Actions()
    service = AutomationService(
        AutomationRepository(api.session), compose(api.session).forms, audit, actions
    )
    audit.capture = service.capture
    return service, actor, org, workspace, user.id, actions


def active_rule(
    service: AutomationService, actor: RequestContext, org: UUID, workspace: UUID, user: UUID
) -> Rule:
    rule = service.create(
        actor,
        org,
        workspace,
        None,
        "Notify",
        RuleDefinition(
            trigger="task.created", actions=[NotifyAction(kind="notify", recipients=[user])]
        ),
    )
    preview = service.activate(actor, org, workspace, rule.id, 1, 1, True, None)
    activated = service.activate(
        actor, org, workspace, rule.id, 1, 1, False, preview.content_sha256
    )
    assert activated.activator_id == user
    return service.get(actor, org, workspace, rule.id)


def event(org: UUID, workspace: UUID, user: UUID, correlation: UUID) -> OperationalEvent:
    return OperationalEvent(
        id=uuid7(),
        type="task.created",
        occurred_at=datetime.now(UTC),
        organization_id=org,
        workspace_id=workspace,
        actor_id=user,
        correlation_id=correlation,
        aggregate_type="task",
        aggregate_id=uuid7(),
        payload=EventContext(),
    )


def test_pinned_execution_duplicate_capture_and_retirement(api: Api) -> None:
    service, actor, org, workspace, user, actions = setup_service(api)
    rule = active_rule(service, actor, org, workspace, user)
    source = event(org, workspace, user, actor.correlation_id)
    service.capture(source)
    service.capture(source)
    runs = service.store.event_runs(org, source.id)
    assert len(runs) == 1
    assert service.store.event_runs(uuid7(), source.id) == []
    service.retire(actor, org, workspace, rule.id, rule.revision, "stop new matches")
    later = event(org, workspace, user, actor.correlation_id)
    service.capture(later)
    assert service.store.event_runs(org, later.id) == []
    completed = service.execute(org, runs[0].id)
    assert completed.state == "completed"
    assert service.execute(org, runs[0].id) == completed
    assert actions.calls == [(completed.id, 0)]
    assert len(service.store.attempts(org, completed.id)) == 1
    assert len(service.store.receipts(org, completed.id)) == 1
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.type == "automation.action.completed", AuditRow.aggregate_id == completed.id
        )
    )
    assert audit and audit.payload["authorized_by"] == str(user)
    assert audit.payload["run_id"] == str(completed.id)


def test_revoked_delegation_dead_letter_and_replay_history(api: Api) -> None:
    service, actor, org, workspace, user, actions = setup_service(api)
    active_rule(service, actor, org, workspace, user)
    source = event(org, workspace, user, actor.correlation_id)
    service.capture(source)
    run = service.store.event_runs(org, source.id)[0]
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == user)
        .values(revoked=True)
    )
    with pytest.raises(ServiceError, match="access_denied"):
        service.execute(org, run.id)
    assert not actions.calls
    failed = service.failed(org, run.id, "delegation_revoked", False)
    assert failed.state == "dead_letter" and failed.attempts == 1
    with pytest.raises(ServiceError):
        service.replay(actor, org, workspace, run.id, "permission still revoked")
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == user)
        .values(revoked=False)
    )
    replay = service.replay(actor, org, workspace, run.id, "access restored")
    assert replay.attempts == 1
    assert service.execute(org, run.id).attempts == 2
    assert [item.outcome for item in service.store.attempts(org, run.id)] == [
        "dead_letter",
        "completed",
    ]


def test_database_immutability_and_guarded_rollback(api: Api) -> None:
    service, actor, org, workspace, user, _ = setup_service(api)
    rule = active_rule(service, actor, org, workspace, user)
    source = event(org, workspace, user, actor.correlation_id)
    service.capture(source)
    version = service.store.version(org, workspace, rule.id, 1)
    assert version
    for sql, identifier in (
        ("UPDATE outbox_events SET envelope='{}' WHERE id=:id", source.id),
        ("DELETE FROM outbox_events WHERE id=:id", source.id),
        (
            "UPDATE automation_versions SET definition='{}',revision=revision+1 WHERE id=:id",
            version.id,
        ),
        ("TRUNCATE automation_rules CASCADE", rule.id),
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql), {"id": identifier})
    run = service.store.event_runs(org, source.id)[0]
    with pytest.raises(DBAPIError), api.session.begin_nested():
        service.store.add_run(run.model_copy(update={"id": uuid7(), "delegator_id": uuid7()}))
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("8323b0dbac0e")
    assert migration
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        migration.module.downgrade()
    assert service.store.event(org, source.id) == source


def test_source_transaction_captures_exact_form_pin_and_rolls_back(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    identifier = UUID(draft(api, route, form))
    captured = api.session.scalar(
        select(EventRow).where(
            EventRow.organization_id == org, EventRow.type == "submission.created"
        )
    )
    assert captured
    source = OperationalEvent.model_validate(captured.envelope)
    assert source.payload.form_id == UUID(form) and source.payload.form_number == 1
    assert source.payload.submission_id == identifier and source.workspace_id == workspace
    services = compose(api.session)
    user = api.session.scalar(select(UserRow).where(UserRow.organization_id == org))
    assert user
    actor = RequestContext(Principal(user.issuer, user.subject), uuid7(), uuid7())
    rolled_back: UUID | None = None
    with pytest.raises(RuntimeError), api.session.begin_nested():
        row = services.submissions.create(actor, org, workspace, UUID(form), 1)
        event_row = api.session.scalar(
            select(EventRow).where(
                EventRow.envelope["payload"]["submission_id"].astext == str(row.id)
            )
        )
        assert event_row
        rolled_back = event_row.id
        raise RuntimeError("abort whole source transaction")
    assert rolled_back and AutomationRepository(api.session).event(org, rolled_back) is None


def test_workspace_admin_can_draft_but_cannot_delegate_activation(api: Api) -> None:
    service, _, org, workspace, user, _ = setup_service(api)
    token = api.invitation(org, workspace, "WorkspaceAdmin")
    invitee = api.accept(org, token)
    identity = api.session.scalar(select(UserRow).where(UserRow.id == invitee))
    assert identity
    actor = RequestContext(Principal(identity.issuer, identity.subject), uuid7(), uuid7())
    rule = service.create(
        actor,
        org,
        workspace,
        None,
        "Draft",
        RuleDefinition(
            trigger="task.created", actions=[NotifyAction(kind="notify", recipients=[user])]
        ),
    )
    with pytest.raises(ServiceError, match="access_denied"):
        service.activate(actor, org, workspace, rule.id, 1, 1, True, None)


def test_loop_condition_retry_limits_and_immutable_attempts(api: Api) -> None:
    service, actor, org, workspace, user, actions = setup_service(api)
    rule = active_rule(service, actor, org, workspace, user)
    version = service.store.version(org, workspace, rule.id, 1)
    assert version
    loop = event(org, workspace, user, actor.correlation_id).model_copy(
        update={"causation_path": [version.id]}
    )
    service.capture(loop)
    assert service.store.event_runs(org, loop.id) == []
    source = event(org, workspace, user, actor.correlation_id)
    service.capture(source)
    run = service.store.event_runs(org, source.id)[0]
    for attempt in range(1, 9):
        failed = service.failed(org, run.id, "temporary_dependency", True)
        assert failed.attempts == attempt
        assert failed.state == ("dead_letter" if attempt == 8 else "retry")
    assert not actions.calls
    assert len(service.store.attempts(org, run.id)) == 8
    for sql in (
        "UPDATE automation_attempts SET error_code='rewritten' WHERE run_id=:id",
        "DELETE FROM automation_attempts WHERE run_id=:id",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql), {"id": run.id})


class Publisher:
    def __init__(self) -> None:
        self.messages: list[DeliveryMessage] = []

    def publish(self, message: DeliveryMessage) -> None:
        self.messages.append(message)


def test_dispatch_crash_republishes_scoped_ids_without_losing_intent(api: Api) -> None:
    service, actor, org, workspace, user, _ = setup_service(api)
    source = event(org, workspace, user, actor.correlation_id)
    service.capture(source)
    publisher = Publisher()
    with pytest.raises(RuntimeError), api.session.begin_nested():
        assert service.dispatch(org, publisher) == 2
        raise RuntimeError("crash after broker publish before transaction commit")
    assert service.dispatch(org, publisher) == 2
    assert len(publisher.messages) == 4
    assert publisher.messages[:2] == publisher.messages[2:]
    assert all(message.organization_id == org for message in publisher.messages)
    assert service.dispatch(org, publisher) == 0
    assert service.dispatch(uuid7(), publisher) == 0
