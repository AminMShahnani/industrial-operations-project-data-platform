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
    TagAction,
)
from operations.modules.automation.application.events import DeliveryMessage, OperationalEvent
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.projects.application.contracts import AnnotationValue, ProjectAnnotation
from operations.modules.projects.infrastructure.persistence import ProjectRepository
from operations.worker import process_automation
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase6_actions import activate, context

pytestmark = pytest.mark.integration


def setup(api: Api) -> tuple[UUID, UUID, UUID, RequestContext, str]:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    actor, _ = context(api, org)
    return (
        org,
        workspace,
        identifier,
        actor,
        f"/api/v1/organizations/{org}/workspaces/{workspace}/projects/{identifier}",
    )


def source(
    api: Api, org: UUID, workspace: UUID, project: UUID, actor: RequestContext
) -> OperationalEvent:
    event = OperationalEvent(
        id=uuid7(),
        type="integration.event",
        organization_id=org,
        workspace_id=workspace,
        project_id=project,
        occurred_at=datetime.now(UTC),
        actor_id=compose(api.session).authorization.user(actor, org).id,
        correlation_id=actor.correlation_id,
        aggregate_type="integration",
        aggregate_id=uuid7(),
    )
    compose(api.session).automation.capture(event)
    return event


def test_action_exact_scope_duplicates_kind_case_and_retained_provenance(api: Api) -> None:
    org, workspace, identifier, actor, route = setup(api)
    services = compose(api.session)
    actions: list[AutomationAction] = [
        TagAction(kind="append_tag", value="Ready"),
        TagAction(kind="append_tag", value="Ready"),
        TagAction(kind="append_flag", value="Ready"),
        TagAction(kind="append_tag", value="ready"),
    ]
    rule = activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(trigger="integration.event", actions=actions),
    )
    before = services.projects.require_access(actor, org, workspace, identifier, "project.read")
    event = source(api, org, workspace, identifier, actor)
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    process_automation(api.session, message)
    page = api.client.get(route + "/annotations", headers=api.headers("admin"))
    assert page.status_code == 200, page.text
    rows = page.json()["items"]
    assert [(row["kind"], row["value"]) for row in rows] == [
        ("tag", "Ready"),
        ("flag", "Ready"),
        ("tag", "ready"),
    ]
    run = services.automation.store.event_runs(org, event.id)[0]
    receipts = services.automation.store.receipts(org, run.id)
    assert len(receipts) == 4 and receipts[0].target_id == receipts[1].target_id == UUID(
        rows[0]["id"]
    )
    for row in rows:
        audit = api.session.get(AuditRow, UUID(row["id"]))
        assert audit and audit.actor_id == UUID(row["created_by_id"])
        assert (
            audit.payload["run_id"] == str(run.id)
            and audit.payload["authorization_kind"] == "delegated_automation"
        )
        assert audit.aggregate_id == identifier and audit.payload["target_id"] == row["id"]
        assert audit.correlation_id == event.correlation_id
    # Another event/rule retains first-append evidence and its own receipt.
    second = source(api, org, workspace, identifier, actor)
    assert (
        process_automation(
            api.session,
            DeliveryMessage(organization_id=org, delivery_id=delivery_id(second.id, "automation")),
        ).state
        == "completed"
    )
    assert (
        api.client.get(route + "/annotations", headers=api.headers("admin")).json() == page.json()
    )
    assert (
        services.projects.require_access(actor, org, workspace, identifier, "project.read")
        == before
    )
    assert services.automation.store.rule(org, workspace, rule.id)


def test_project_read_scope_and_fresh_revocation(api: Api) -> None:
    org, workspace, identifier, actor, route = setup(api)
    services = compose(api.session)
    row = services.projects.append_annotation(
        actor, org, workspace, identifier, AnnotationValue(kind="flag", value="needs_review")
    )
    user = api.accept(org, api.invitation(org, workspace))
    headers = api.headers("invitee", "invitee@example.com")
    assert api.client.get(route + "/annotations", headers=headers).status_code == 403
    granted = api.client.post(
        route + "/memberships",
        headers=api.headers("admin"),
        json={"user_id": str(user), "role": "Viewer"},
    )
    assert granted.status_code == 201, granted.text
    visible = api.client.get(route + "/annotations", headers=headers)
    assert visible.status_code == 200 and visible.json()["items"][0]["id"] == str(row.id)
    viewer = RequestContext(Principal("https://identity.example.test", "invitee"), uuid7(), uuid7())
    with pytest.raises(ServiceError, match="access_denied"):
        services.projects.append_annotation(
            viewer, org, workspace, identifier, AnnotationValue(kind="tag", value="forbidden")
        )
    revoked = api.client.post(
        route + f"/memberships/{granted.json()['id']}/revoke", headers=api.headers("admin")
    )
    assert revoked.status_code == 204, revoked.text
    assert api.client.get(route + "/annotations", headers=headers).status_code == 403
    assert (
        services.projects.store.annotation(
            org, workspace, identifier, AnnotationValue(kind="flag", value="needs_review")
        )
        == row
    )
    foreign = api.organization("otheradmin")
    other_workspace = api.workspace(foreign, "otheradmin")
    wrong = api.client.get(
        f"/api/v1/organizations/{foreign}/workspaces/{other_workspace}/projects/{identifier}/annotations",
        headers=api.headers("otheradmin"),
    )
    assert wrong.status_code == 404


def test_filtered_annotation_pages_and_invalid_cursors(api: Api) -> None:
    org, workspace, identifier, actor, route = setup(api)
    services = compose(api.session)
    expected: list[str] = []
    flag = None
    for number in range(104):
        if number % 25 == 0:
            flag = services.projects.append_annotation(
                actor,
                org,
                workspace,
                identifier,
                AnnotationValue(kind="flag", value=f"flag_{number}"),
            )
        row = services.projects.append_annotation(
            actor, org, workspace, identifier, AnnotationValue(kind="tag", value=f"tag_{number}")
        )
        expected.append(str(row.id))
    first = api.client.get(
        route + "/annotations", headers=api.headers("admin"), params={"kind": "tag"}
    ).json()
    second = api.client.get(
        route + "/annotations",
        headers=api.headers("admin"),
        params={"kind": "tag", "cursor": first["next_cursor"]},
    ).json()
    assert (
        len(first["items"]) == 100 and len(second["items"]) == 4 and second["next_cursor"] is None
    )
    assert [row["id"] for row in first["items"] + second["items"]] == expected
    other_project = UUID(project(api, org, workspace))
    foreign = services.projects.append_annotation(
        actor, org, workspace, other_project, AnnotationValue(kind="tag", value="other")
    )
    assert flag
    for cursor in (uuid7(), foreign.id, flag.id):
        invalid = api.client.get(
            route + "/annotations",
            headers=api.headers("admin"),
            params={"kind": "tag", "cursor": str(cursor)},
        )
        assert (
            invalid.status_code == 422
            and invalid.json()["code"] == "project_annotation_cursor_invalid"
        )


def test_annotation_bound_preserves_duplicate_evidence(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, identifier, actor, _ = setup(api)
    services = compose(api.session)
    value = AnnotationValue(kind="tag", value="existing")
    existing = services.projects.append_annotation(actor, org, workspace, identifier, value)
    monkeypatch.setattr(
        ProjectRepository, "annotation_count", lambda self, org, workspace, project: 1000
    )
    assert services.projects.append_annotation(actor, org, workspace, identifier, value) == existing
    with pytest.raises(ServiceError, match="project_annotation_limit"):
        services.projects.append_annotation(
            actor, org, workspace, identifier, AnnotationValue(kind="flag", value="new")
        )
    assert services.projects.annotations(actor, org, workspace, identifier).items == [existing]


def test_second_action_failure_rolls_back_annotations_audits_receipts(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, identifier, actor, _ = setup(api)
    services = compose(api.session)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="integration.event",
            actions=[
                TagAction(kind="append_tag", value="first"),
                TagAction(kind="append_flag", value="second"),
            ],
        ),
    )
    event = source(api, org, workspace, identifier, actor)
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation"))
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
    run = services.automation.store.event_runs(org, event.id)[0]
    assert not services.projects.annotations(actor, org, workspace, identifier).items
    assert not services.automation.store.receipts(org, run.id)
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(
                AuditRow.organization_id == org,
                AuditRow.type.in_(["project.tag.appended", "project.flag.appended"]),
            )
        )
        == 0
    )
    monkeypatch.setattr(ApplicationActions, "execute", original)
    due = datetime.now(UTC) - timedelta(seconds=1)
    services.automation.store.save_run(run.model_copy(update={"next_at": due}))
    delivery = services.automation.store.delivery(org, message.delivery_id)
    assert delivery
    services.automation.store.save_delivery(delivery.model_copy(update={"next_at": due}))
    assert process_automation(api.session, message).state == "completed"
    assert len(services.projects.annotations(actor, org, workspace, identifier).items) == 2


def test_workspace_rule_refuses_inferred_annotation_target(api: Api) -> None:
    org, workspace, _, _, _ = setup(api)
    endpoint = f"/api/v1/organizations/{org}/workspaces/{workspace}/automation-rules"
    result = api.client.post(
        endpoint,
        headers=api.headers("admin"),
        json={
            "name": "Missing target",
            "definition": {
                "trigger": "integration.event",
                "actions": [{"kind": "append_tag", "value": "label"}],
            },
        },
    )
    assert (
        result.status_code == 422
        and result.json()["code"] == "automation_project_annotation_required"
    )


def test_terminal_project_refuses_annotation_writes(api: Api) -> None:
    org, workspace, identifier, actor, route = setup(api)
    services = compose(api.session)
    value = AnnotationValue(kind="tag", value="historic")
    row = services.projects.append_annotation(actor, org, workspace, identifier, value)
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="integration.event", actions=[TagAction(kind="append_flag", value="blocked")]
        ),
    )
    event = source(api, org, workspace, identifier, actor)
    services.projects.transition(actor, org, workspace, identifier, "archived", 1, "freeze")
    with pytest.raises(ServiceError, match="terminal_project"):
        services.projects.append_annotation(actor, org, workspace, identifier, value)
    assert api.client.get(route + "/annotations", headers=api.headers("admin")).json()["items"][0][
        "id"
    ] == str(row.id)
    assert (
        process_automation(
            api.session,
            DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation")),
        ).state
        == "dead_letter"
    )
    assert services.projects.annotations(actor, org, workspace, identifier).items == [row]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE project_annotations SET value='rewrite' WHERE id=:id",
        "DELETE FROM project_annotations WHERE id=:id",
        "TRUNCATE project_annotations",
    ],
)
def test_annotation_immutable_history_and_guarded_rollback(api: Api, statement: str) -> None:
    org, workspace, identifier, actor, _ = setup(api)
    service = compose(api.session).projects
    row = service.append_annotation(
        actor, org, workspace, identifier, AnnotationValue(kind="flag", value="retained")
    )
    with pytest.raises(DBAPIError, match="history is retained"), api.session.begin_nested():
        api.session.execute(text(statement), {"id": row.id})
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("e49b7d83af20")
    assert revision
    with (
        pytest.raises(DBAPIError, match="Retained project annotations"),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()
    assert service.annotations(actor, org, workspace, identifier).items == [row]
    assert api.session.get(AuditRow, row.id)


def test_annotation_insert_requires_exact_audit_binding(api: Api) -> None:
    org, workspace, identifier, actor, _ = setup(api)
    user = compose(api.session).authorization.user(actor, org)
    row = ProjectAnnotation(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        project_id=identifier,
        kind="tag",
        value="unaudited",
        created_by_id=user.id,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(DBAPIError, match="requires exact audit"), api.session.begin_nested():
        compose(api.session).projects.store.add_annotation(row)
    assert not compose(api.session).projects.annotations(actor, org, workspace, identifier).items


def test_revoked_original_delegation_preserves_existing_annotations(api: Api) -> None:
    org, workspace, identifier, actor, _ = setup(api)
    services = compose(api.session)
    retained = services.projects.append_annotation(
        actor, org, workspace, identifier, AnnotationValue(kind="tag", value="retained")
    )
    activate(
        api,
        actor,
        org,
        workspace,
        identifier,
        RuleDefinition(
            trigger="integration.event", actions=[TagAction(kind="append_flag", value="blocked")]
        ),
    )
    event = source(api, org, workspace, identifier, actor)
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
    user = services.authorization.user(actor, org)
    revoked = api.client.post(
        f"/api/v1/organizations/{org}/users/{user.id}/revoke",
        headers=api.headers("invitee", "invitee@example.com"),
    )
    assert revoked.status_code == 204, revoked.text
    assert (
        process_automation(
            api.session,
            DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation")),
        ).state
        == "dead_letter"
    )
    run = services.automation.store.event_runs(org, event.id)[0]
    assert not services.automation.store.receipts(org, run.id)
    assert services.projects.store.annotation_count(org, workspace, identifier) == 1
    assert api.session.get(AuditRow, retained.id)


def test_empty_annotation_migration_roundtrip_preserves_existing_audits(api: Api) -> None:
    org, _, _, _, _ = setup(api)
    before = api.session.scalar(
        select(func.count()).select_from(AuditRow).where(AuditRow.organization_id == org)
    )
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("e49b7d83af20")
    assert revision
    with Operations.context(MigrationContext.configure(api.session.connection())):
        revision.module.downgrade()
        assert api.session.scalar(text("SELECT to_regclass('project_annotations')")) is None
        assert (
            api.session.scalar(
                select(func.count()).select_from(AuditRow).where(AuditRow.organization_id == org)
            )
            == before
        )
        revision.module.upgrade()
    assert api.session.scalar(text("SELECT to_regclass('project_annotations')"))
