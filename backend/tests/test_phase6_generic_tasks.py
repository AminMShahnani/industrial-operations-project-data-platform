from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.actions import ApplicationActions
from operations.modules.automation.application.contracts import (
    AutomationAction,
    Rule,
    RuleDefinition,
    Run,
    TaskAction,
)
from operations.modules.automation.application.events import DeliveryMessage, OperationalEvent
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import EventRow
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.scheduling.application.contracts import Assignment
from operations.modules.submissions.infrastructure.persistence import SubmissionRow
from operations.modules.tasks.application.contracts import GenericTaskDefinition
from operations.modules.tasks.infrastructure.persistence import TaskRow
from operations.worker import process_automation
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase4_api import activate as activate_schedule
from test_phase4_api import generate, schedule_setup
from test_phase6_actions import activate, context

pytestmark = pytest.mark.integration


def fixture(
    api: Api, *, second: bool = False
) -> tuple[UUID, UUID, RequestContext, OperationalEvent, DeliveryMessage]:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    action = TaskAction(
        kind="create_task",
        name="Inspect shared work",
        assignments=[Assignment(kind="user", target_id=user)],
        due_seconds=60,
    )
    activate(
        api,
        actor,
        org,
        workspace,
        None,
        RuleDefinition(
            trigger="integration.event", actions=[action, action] if second else [action]
        ),
    )
    event = OperationalEvent(
        id=uuid7(),
        type="integration.event",
        organization_id=org,
        workspace_id=workspace,
        occurred_at=datetime.now(UTC) - timedelta(hours=1),
        actor_id=user,
        correlation_id=actor.correlation_id,
        aggregate_type="integration",
        aggregate_id=uuid7(),
    )
    compose(api.session).automation.capture(event)
    return (
        org,
        workspace,
        actor,
        event,
        DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation")),
    )


def test_generic_action_consumer_claim_complete_and_immutable_evidence(api: Api) -> None:
    org, workspace, actor, event, message = fixture(api)
    services = compose(api.session)
    assert process_automation(api.session, message).state == "completed"
    process_automation(api.session, message)
    tasks, _ = services.tasks.inbox(actor, org, workspace, None, "all", "personal", None, None)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind == "generic" and task.form_id is None and task.schedule_id is None
    assert task.due_at == event.occurred_at + timedelta(seconds=60)
    assert task.recipient_ids == [services.authorization.user(actor, org).id]
    run = services.automation.store.event_runs(org, event.id)[0]
    assert services.automation.store.receipts(org, run.id)[0].target_id == task.id
    source = api.session.scalar(
        select(AuditRow).where(AuditRow.aggregate_id == task.id, AuditRow.type == "task.created")
    )
    assert source and source.payload["run_id"] == str(run.id)
    caused = services.automation.store.event(org, source.id)
    assert caused and caused.causation_id == event.id and caused.payload.form_id is None
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}/tasks/{task.id}"
    headers = api.headers("admin")
    assert (
        api.client.post(
            route + "/complete", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 403
    )
    claimed = api.client.post(route + "/start", headers=headers, json={"expected_revision": 1})
    assert claimed.status_code == 200 and claimed.json()["submission_id"] is None
    assert (
        api.client.post(
            route + "/complete", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 409
    )
    completed = api.client.post(route + "/complete", headers=headers, json={"expected_revision": 2})
    assert completed.status_code == 200 and completed.json()["state"] == "completed"
    assert completed.json()["completed_at"] and completed.json()["revision"] == 3
    assert (
        api.client.post(route + "/complete", headers=headers, json={"expected_revision": 2}).json()
        == completed.json()
    )
    assert (
        api.client.post(
            route + "/start", headers=headers, json={"expected_revision": 3}
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            route + "/cancel",
            headers=headers,
            json={"expected_revision": 3, "reason": "too late", "dry_run": False},
        ).status_code
        == 409
    )
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(SubmissionRow)
            .where(SubmissionRow.organization_id == org)
        )
        == 0
    )
    audits = api.session.scalars(
        select(AuditRow).where(AuditRow.aggregate_id == task.id, AuditRow.type == "task.completed")
    ).all()
    assert len(audits) == 1 and audits[0].actor_id == task.recipient_ids[0]
    assert (
        services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 0
    )


def test_generic_shared_task_owner_and_fresh_group_revocation(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    invitee = api.accept(org, api.invitation(org, workspace, role="Contributor"))
    actor, _ = context(api, org)
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}"
    headers = api.headers("admin")
    group = api.client.post(
        route + "/groups", headers=headers, json={"name": "Shared team", "kind": "team"}
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    peer = api.accept(
        org,
        api.invitation(org, workspace, role="Contributor", email="peer@example.com"),
        "peer",
        "peer@example.com",
    )
    peer_membership = api.client.post(
        route + f"/groups/{group_id}/memberships",
        headers=headers,
        json={
            "user_id": str(peer),
            "manager": False,
        },
    )
    assert peer_membership.status_code == 201, peer_membership.text
    membership = api.client.post(
        route + f"/groups/{group_id}/memberships",
        headers=headers,
        json={"user_id": str(invitee), "manager": False},
    )
    assert membership.status_code == 201, membership.text
    services = compose(api.session)
    definition = GenericTaskDefinition(
        origin_id=uuid7(),
        name="Shared acknowledgement",
        assignments=[Assignment(kind="team", target_id=UUID(group_id))],
        occurs_at=datetime.now(UTC) - timedelta(minutes=5),
        due_seconds=60,
    )
    task = services.tasks.create_generic(actor, org, workspace, None, definition)[0]
    endpoint = route + f"/tasks/{task.id}"
    user_headers = api.headers("invitee", "invitee@example.com")
    claimed = api.client.post(
        endpoint + "/start", headers=user_headers, json={"expected_revision": 1}
    )
    assert claimed.status_code == 200, claimed.text
    assert (
        api.client.post(
            endpoint + "/start",
            headers=api.headers("peer", "peer@example.com"),
            json={"expected_revision": 1},
        ).status_code
        == 409
    )
    # A manager cannot satisfy somebody else's acknowledgement.
    assert (
        api.client.post(
            endpoint + "/complete", headers=headers, json={"expected_revision": 2}
        ).status_code
        == 403
    )
    peer_completion = api.client.post(
        endpoint + "/complete",
        headers=api.headers("peer", "peer@example.com"),
        json={"expected_revision": 2},
    )
    assert (
        peer_completion.status_code == 403
        and peer_completion.json()["code"] == "task_claimant_required"
    )
    removed = api.client.post(
        route + f"/groups/{group_id}/memberships/{membership.json()['id']}/revoke", headers=headers
    )
    assert removed.status_code == 204, removed.text
    revoked = api.client.post(
        endpoint + "/complete", headers=user_headers, json={"expected_revision": 2}
    )
    assert revoked.status_code == 403 and revoked.json()["code"] == "task_assignment_revoked"
    row = services.tasks.store.get(org, workspace, task.id)
    assert row and row.state == "in_progress" and row.claimant_id == invitee


def test_generic_create_duplicate_preserves_snapshot_and_scope(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    services = compose(api.session)
    definition = GenericTaskDefinition(
        origin_id=uuid7(),
        name="Explicit work",
        assignments=[Assignment(kind="role", role="OrganizationAdmin")],
        occurs_at=datetime.now(UTC),
        due_seconds=60,
    )
    task = services.tasks.create_generic(actor, org, workspace, None, definition)[0]
    invitation = api.client.post(
        f"/api/v1/organizations/{org}/invitations",
        headers=api.headers("admin"),
        json={
            "email": "invitee@example.com",
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(org),
        },
    )
    assert invitation.status_code == 201, invitation.text
    new_admin = api.accept(org, invitation.json()["token"])
    duplicate = services.tasks.create_generic(actor, org, workspace, None, definition)[0]
    assert (
        duplicate == task
        and duplicate.recipient_ids == [user]
        and new_admin not in duplicate.recipient_ids
    )
    with pytest.raises(ServiceError, match="task_creation_conflict"):
        services.tasks.create_generic(
            actor, org, workspace, None, definition.model_copy(update={"name": "Changed"})
        )
    foreign = api.organization("otheradmin")
    other_workspace = api.workspace(foreign, "otheradmin")
    wrong = api.client.get(
        f"/api/v1/organizations/{foreign}/workspaces/{other_workspace}/tasks/{task.id}",
        headers=api.headers("otheradmin"),
    )
    assert wrong.status_code == 404


def test_generic_second_action_failure_rolls_back_and_retries_event_time(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, actor, event, message = fixture(api, second=True)
    service = compose(api.session).automation
    original = ApplicationActions.execute

    def fail_second(
        self: ApplicationActions,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None:
        if position == 1:
            raise ServiceError(503, "fixture_transient_dependency")
        return original(self, actor, rule, event, run, position, action)

    monkeypatch.setattr(ApplicationActions, "execute", fail_second)
    assert process_automation(api.session, message).state == "retry"
    run = service.store.event_runs(org, event.id)[0]
    assert not service.store.receipts(org, run.id)
    for model in (TaskRow, AuditRow, EventRow):
        query = select(func.count()).select_from(model).where(model.organization_id == org)
        if model is AuditRow:
            query = query.where(AuditRow.type == "task.created")
        if model is EventRow:
            query = query.where(EventRow.type == "task.created")
        assert api.session.scalar(query) == 0
    monkeypatch.setattr(ApplicationActions, "execute", original)
    due = datetime.now(UTC) - timedelta(seconds=1)
    service.store.save_run(run.model_copy(update={"next_at": due}))
    delivery = service.store.delivery(org, message.delivery_id)
    assert delivery
    service.store.save_delivery(delivery.model_copy(update={"next_at": due}))
    assert process_automation(api.session, message).state == "completed"
    process_automation(api.session, message)
    tasks, _ = compose(api.session).tasks.inbox(
        actor, org, workspace, None, "all", "personal", None, None
    )
    assert len(tasks) == 2 and all(
        task.due_at == event.occurred_at + timedelta(seconds=60) for task in tasks
    )
    assert len(service.store.receipts(org, run.id)) == 2


def test_form_tasks_cannot_use_generic_completion(api: Api) -> None:
    route, schedule, _ = schedule_setup(api)
    activate_schedule(api, route, schedule)
    generate(api, route, schedule)
    task = api.client.get(route + "/tasks", headers=api.headers("admin")).json()["items"][0]
    claimed = api.client.post(
        route + f"/tasks/{task['id']}/start",
        headers=api.headers("admin"),
        json={"expected_revision": 1},
    )
    assert (
        claimed.status_code == 200
        and claimed.json()["kind"] == "form"
        and claimed.json()["submission_id"]
    )
    complete = api.client.post(
        route + f"/tasks/{task['id']}/complete",
        headers=api.headers("admin"),
        json={"expected_revision": 2},
    )
    assert (
        complete.status_code == 409
        and complete.json()["code"] == "form_task_completion_requires_submission"
    )


@pytest.mark.parametrize(
    "mutation",
    ["kind='form'", "name='rewritten'", "state='approved'", "state='completed',completed_at=now()"],
)
def test_generic_database_guards_and_populated_rollback(api: Api, mutation: str) -> None:
    org, workspace, actor, _, message = fixture(api)
    process_automation(api.session, message)
    task = compose(api.session).tasks.inbox(
        actor, org, workspace, None, "all", "personal", None, None
    )[0][0]
    with pytest.raises(DBAPIError), api.session.begin_nested():
        api.session.execute(
            text(f"UPDATE task_occurrences SET {mutation},revision=revision+1 WHERE id=:id"),
            {"id": task.id},
        )
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("d318af6c902e")
    assert revision
    with (
        pytest.raises(DBAPIError, match="Retained generic tasks"),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()
    assert compose(api.session).tasks.store.get(org, workspace, task.id) == task


def test_generic_definition_rejects_form_pins_and_duplicate_targets(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    actor, user = context(api, org)
    endpoint = f"/api/v1/organizations/{org}/workspaces/{workspace}/automation-rules"
    action = {
        "kind": "create_task",
        "name": "Generic",
        "assignments": [{"kind": "user", "target_id": str(user)}],
    }
    response = api.client.post(
        endpoint,
        headers=api.headers("admin"),
        json={
            "name": "Pinned generic",
            "definition": {
                "trigger": "integration.event",
                "actions": [{**action, "form_id": str(uuid7()), "form_number": 1}],
            },
        },
    )
    assert (
        response.status_code == 422 and response.json()["code"] == "generic_task_must_not_pin_form"
    )
    action["assignments"] = [{"kind": "user", "target_id": str(user)}] * 2
    duplicate = api.client.post(
        endpoint,
        headers=api.headers("admin"),
        json={
            "name": "Duplicate",
            "definition": {"trigger": "integration.event", "actions": [action]},
        },
    )
    assert duplicate.status_code == 422


def test_generic_project_lifecycle_and_live_delegation(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, user = context(api, org)
    services = compose(api.session)
    definition = GenericTaskDefinition(
        origin_id=uuid7(),
        name="Project work",
        assignments=[Assignment(kind="user", target_id=user)],
        occurs_at=datetime.now(UTC),
        due_seconds=60,
    )
    task = services.tasks.create_generic(actor, org, workspace, identifier, definition)[0]
    services.tasks.claim(actor, org, workspace, task.id, 1)
    services.projects.transition(actor, org, workspace, identifier, "archived", 1, "freeze work")
    with pytest.raises(ServiceError):
        services.tasks.complete(actor, org, workspace, task.id, 2)
    retained = services.tasks.store.get(org, workspace, task.id)
    assert retained and retained.state == "in_progress"


def test_generic_action_revoked_delegation_produces_no_task(api: Api) -> None:
    org, workspace, actor, event, message = fixture(api)
    user = compose(api.session).authorization.user(actor, org)
    invitation = api.client.post(
        f"/api/v1/organizations/{org}/invitations",
        headers=api.headers("admin"),
        json={
            "email": "invitee@example.com",
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(org),
        },
    )
    assert invitation.status_code == 201, invitation.text
    api.accept(org, invitation.json()["token"])
    revoked = api.client.post(
        f"/api/v1/organizations/{org}/users/{user.id}/revoke",
        headers=api.headers("invitee", "invitee@example.com"),
    )
    assert revoked.status_code == 204, revoked.text
    assert process_automation(api.session, message).state == "dead_letter"
    service = compose(api.session).automation
    run = service.store.event_runs(org, event.id)[0]
    assert run.state == "dead_letter" and not service.store.receipts(org, run.id)
    assert (
        api.session.scalar(
            select(func.count()).select_from(TaskRow).where(TaskRow.organization_id == org)
        )
        == 0
    )


def test_form_history_survives_generic_migration_roundtrip(api: Api) -> None:
    route, schedule, _ = schedule_setup(api)
    activate_schedule(api, route, schedule)
    generate(api, route, schedule)
    before = api.client.get(route + "/tasks", headers=api.headers("admin")).json()["items"][0]
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("d318af6c902e")
    assert revision
    with Operations.context(MigrationContext.configure(api.session.connection())):
        revision.module.downgrade()
        pins = api.session.execute(
            text(
                "SELECT form_id, form_number, schedule_id, state FROM task_occurrences WHERE id=:id"
            ),
            {"id": UUID(before["id"])},
        ).one()
        assert (
            str(pins.form_id) == before["form_id"]
            and str(pins.schedule_id) == before["schedule_id"]
            and pins.state == "open"
        )
        revision.module.upgrade()
    after = api.client.get(route + "/tasks", headers=api.headers("admin")).json()["items"][0]
    assert after == before
