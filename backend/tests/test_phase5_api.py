from copy import deepcopy
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.infrastructure.persistence import UserRow
from operations.modules.submissions.infrastructure.persistence import SubmissionRow
from operations.modules.workflows.infrastructure.runtime import (
    ActionRow,
    InstanceRow,
    NotificationRow,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase3_api import draft, publish, schema, setup
from test_phase4_api import activate as activate_schedule
from test_phase4_api import generate, schedule_setup

pytestmark = pytest.mark.integration


def definition(form: str, recipients: list[UUID], mode: str = "one") -> dict[str, object]:
    return {
        "form_id": form,
        "form_number": 1,
        "nodes": [
            {"key": "start", "name": "Start", "kind": "start"},
            {
                "key": "approve",
                "name": "Approval",
                "kind": "approval",
                "assignments": [{"kind": "user", "target_id": str(user)} for user in recipients],
                "policy": {"mode": mode},
                "return_to": "submitter",
            },
            {"key": "end", "name": "End", "kind": "end"},
        ],
        "transitions": [
            {"source": "start", "target": "approve"},
            {"source": "approve", "target": "end"},
        ],
    }


def create_workflow(api: Api, route: str, body: dict[str, object]) -> str:
    result = api.client.post(
        route + "/workflows",
        headers=api.headers("admin"),
        json={"name": "Independent approval", "definition": body},
    )
    assert result.status_code == 201, result.text
    return str(result.json()["id"])


def activate(api: Api, route: str, workflow: str, number: int = 1) -> None:
    url = route + f"/workflows/{workflow}/versions/{number}/activate"
    preview = api.client.post(url, headers=api.headers("admin"), json={"expected_revision": 1})
    assert preview.status_code == 200, preview.text
    result = api.client.post(
        url,
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "dry_run": False,
            "expected_sha256": preview.json()["content_sha256"],
        },
    )
    assert result.status_code == 200, result.text


def submit(api: Api, route: str, form: str) -> tuple[str, dict[str, object]]:
    identifier = draft(api, route, form)
    saved = api.client.put(
        route + f"/submissions/{identifier}",
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "values": {"fields": {"quantity": 5, "acknowledge": "I acknowledge"}},
        },
    )
    assert saved.status_code == 200, saved.text
    result = api.client.post(
        route + f"/submissions/{identifier}/submit",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Reviewed data"},
    )
    assert result.status_code == 200, result.text
    history = api.client.get(
        route + f"/submissions/{identifier}/workflow", headers=api.headers("admin")
    )
    assert history.status_code == 200, history.text
    return identifier, dict(history.json()["instance"])


def reviewer(
    api: Api, org: UUID, workspace: UUID, subject: str = "reviewer", role: str = "Approver"
) -> UUID:
    email = subject + "@example.com"
    return api.accept(org, api.invitation(org, workspace, role, email=email), subject, email)


@pytest.mark.parametrize("mode", ["all", "quorum", "sequential"])
def test_complete_distinct_vote_policies(api: Api, mode: str) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    voters = [reviewer(api, org, workspace, name) for name in ("first", "second", "third")]
    body = definition(form, voters, mode)
    if mode == "quorum":
        nodes = body["nodes"]
        assert isinstance(nodes, list)
        nodes[1]["policy"] = {"mode": "quorum", "quorum": 2}
    workflow = create_workflow(api, route, body)
    activate(api, route, workflow)
    _, row = submit(api, route, form)
    first = action(api, route, row, "first")
    assert first["state"] == "active"
    duplicate = api.client.post(
        route + f"/workflow-instances/{row['id']}/actions",
        headers=api.headers("first", "first@example.com"),
        json={
            "expected_revision": first["revision"],
            "idempotency_key": str(uuid7()),
            "kind": "approve",
            "reason": "Duplicate vote cannot satisfy policy",
        },
    )
    assert duplicate.status_code == 409
    second = action(api, route, first, "second")
    if mode == "quorum":
        assert second["state"] == "approved"
    else:
        assert second["state"] == "active"
        assert action(api, route, second, "third")["state"] == "approved"
    assert api.session.scalar(select(func.count()).select_from(ActionRow)) == (
        2 if mode == "quorum" else 3
    )


@pytest.mark.parametrize("strategy", ["team", "project_role", "department_role"])
def test_scoped_assignment_and_live_membership_revocation(api: Api, strategy: str) -> None:
    org, workspace, route, form = setup(api)
    voter = reviewer(api, org, workspace)
    identifier = project(api, org, workspace)
    # A project workflow must pin a form in that same project.
    form_result = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={
            "name": "Project report",
            "project_id": identifier,
            "definition": {
                "sections": [
                    {
                        "key": "main",
                        "label": "Main",
                        "components": [
                            {"key": "quantity", "label": "Quantity", "kind": "integer"},
                            {"key": "acknowledge", "label": "Acknowledgement", "kind": "signature"},
                        ],
                    }
                ]
            },
        },
    )
    assert form_result.status_code == 201, form_result.text
    form = form_result.json()["id"]
    publish(api, route, form)
    project_route = route + f"/projects/{identifier}"
    if strategy == "project_role":
        grant = api.client.post(
            project_route + "/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(voter), "role": "Approver"},
        )
        assert grant.status_code == 201, grant.text
        revoke = project_route + f"/memberships/{grant.json()['id']}/revoke"
        target = {"kind": "project_role", "role": "Approver"}
    else:
        kind = "team" if strategy == "team" else "department"
        group = api.client.post(
            route + "/groups",
            headers=api.headers("admin"),
            json={"kind": kind, "name": "Assigned group"},
        )
        assert group.status_code == 201, group.text
        group_id = group.json()["id"]
        member = api.client.post(
            route + f"/groups/{group_id}/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(voter)},
        )
        assert member.status_code == 201, member.text
        revoke = route + f"/groups/{group_id}/memberships/{member.json()['id']}/revoke"
        if strategy == "department_role":
            grant = api.client.post(
                project_route + "/department-grants",
                headers=api.headers("admin"),
                json={"department_id": group_id, "role": "Approver"},
            )
        else:
            grant = api.client.post(
                project_route + "/memberships",
                headers=api.headers("admin"),
                json={"user_id": str(voter), "role": "Approver"},
            )
        assert grant.status_code == 201, grant.text
        target = {"kind": strategy, "target_id": group_id}
        if strategy == "department_role":
            target["role"] = "Approver"
    body = definition(form, [voter])
    nodes = body["nodes"]
    assert isinstance(nodes, list)
    nodes[1]["assignments"] = [target]
    created = api.client.post(
        route + "/workflows",
        headers=api.headers("admin"),
        json={"name": "Scoped assignment", "project_id": identifier, "definition": body},
    )
    assert created.status_code == 201, created.text
    activate(api, route, created.json()["id"])
    _, row = submit(api, route, form)
    inbox = api.client.get(
        route + "/workflow-inbox",
        headers=api.headers("reviewer", "reviewer@example.com"),
        params={"project_id": identifier},
    )
    assert inbox.status_code == 200 and inbox.json()["items"][0]["id"] == row["id"]
    assert api.client.post(revoke, headers=api.headers("admin")).status_code == 204
    denied = api.client.post(
        route + f"/workflow-instances/{row['id']}/actions",
        headers=api.headers("reviewer", "reviewer@example.com"),
        json={
            "expected_revision": row["revision"],
            "idempotency_key": str(uuid7()),
            "kind": "approve",
            "reason": "Removed member",
        },
    )
    assert denied.status_code == 403
    assert api.session.scalar(select(func.count()).select_from(ActionRow)) == 0
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("71db385e7a02")
    assert migration is not None
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        migration.module.downgrade()


def test_deterministic_decision_notification_and_binding_collision(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    voter = reviewer(api, org, workspace)
    body = definition(form, [voter])
    nodes = body["nodes"]
    assert isinstance(nodes, list)
    nodes.extend(
        [
            {
                "key": "gate",
                "name": "Snapshot condition",
                "kind": "decision",
                "condition": {
                    "op": "gt",
                    "args": [{"op": "field", "key": "quantity"}, {"op": "literal", "value": 0}],
                },
            },
            {
                "key": "notify",
                "name": "Notify",
                "kind": "notify",
                "assignments": [{"kind": "user", "target_id": str(voter)}],
            },
        ]
    )
    body["transitions"] = [
        {"source": "start", "target": "gate"},
        {"source": "gate", "target": "approve", "outcome": "true"},
        {"source": "gate", "target": "end", "outcome": "false"},
        {"source": "approve", "target": "notify"},
        {"source": "notify", "target": "end"},
    ]
    workflow = create_workflow(api, route, body)
    activate(api, route, workflow)
    conflicting = create_workflow(api, route, deepcopy(body))
    preview = api.client.post(
        route + f"/workflows/{conflicting}/versions/1/activate",
        headers=api.headers("admin"),
        json={"expected_revision": 1},
    )
    assert preview.status_code == 200
    collision = api.client.post(
        route + f"/workflows/{conflicting}/versions/1/activate",
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "dry_run": False,
            "expected_sha256": preview.json()["content_sha256"],
        },
    )
    assert collision.status_code == 409
    _, row = submit(api, route, form)
    assert row["current_node"] == "approve"
    assert action(api, route, row, "reviewer")["state"] == "approved"
    intent = api.session.scalar(select(NotificationRow))
    assert intent is not None and intent.recipient_ids == [str(voter)]
    with pytest.raises(DBAPIError), api.session.begin_nested():
        api.session.execute(text("UPDATE workflow_notifications SET node_key='changed'"))
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("20bfc93ae828")
    assert migration is not None
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        migration.module.downgrade()
    assert api.session.scalar(select(func.count()).select_from(InstanceRow)) == 1


def test_return_visits_page_history_without_reusing_previous_votes(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    voters = [reviewer(api, org, workspace, name) for name in ("first", "second")]
    body = definition(form, voters, "all")
    nodes = body["nodes"]
    assert isinstance(nodes, list)
    nodes[1]["return_to"] = "review"
    nodes.append(
        {
            "key": "review",
            "name": "Review",
            "kind": "review",
            "policy": {"mode": "one"},
            "assignments": [{"kind": "user", "target_id": str(voters[0])}],
        }
    )
    body["transitions"] = [
        {"source": "start", "target": "review"},
        {"source": "review", "target": "approve"},
        {"source": "approve", "target": "end"},
    ]
    workflow = create_workflow(api, route, body)
    activate(api, route, workflow)
    _, row = submit(api, route, form)
    for _ in range(51):
        row = action(api, route, row, "first", "review")
        row = action(api, route, row, "first")
        assert row["state"] == "active"
        row = action(api, route, row, "second", "reject")
        assert row["state"] == "active"
    row = action(api, route, row, "first", "review")
    row = action(api, route, row, "first")
    assert row["state"] == "active"  # 51 earlier approvals cannot complete this visit.
    row = action(api, route, row, "second")
    assert row["state"] == "approved"
    url = route + f"/workflow-instances/{row['id']}"
    history = api.client.get(url, headers=api.headers("admin")).json()
    assert len(history["steps"]) == 20 and len(history["actions"]) == 100
    next_steps = api.client.get(
        url, headers=api.headers("admin"), params={"step_cursor": history["next_step_cursor"]}
    ).json()
    assert len(next_steps["steps"]) == 20
    assert {step["id"] for step in history["steps"]}.isdisjoint(
        step["id"] for step in next_steps["steps"]
    )
    next_actions = api.client.get(
        url, headers=api.headers("admin"), params={"action_cursor": history["next_action_cursor"]}
    ).json()
    assert len(next_actions["actions"]) == 56 and next_actions["next_action_cursor"] is None
    assert {entry["id"] for entry in history["actions"]}.isdisjoint(
        entry["id"] for entry in next_actions["actions"]
    )


def test_review_then_snapshot_user_assignment_and_unavailable_manager(api: Api) -> None:
    org, workspace, route, _ = setup(api)
    approver = reviewer(api, org, workspace, "approver")
    review_user = reviewer(api, org, workspace, "reviewer", "Reviewer")
    form_schema = schema()
    sections = form_schema["sections"]
    assert isinstance(sections, list)
    sections[0]["components"].append({"key": "approver", "label": "Approver", "kind": "user"})
    created = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={"name": "Assigned snapshot", "definition": form_schema},
    )
    assert created.status_code == 201, created.text
    form = created.json()["id"]
    publish(api, route, form)
    body = definition(form, [approver])
    nodes = body["nodes"]
    assert isinstance(nodes, list)
    nodes[1]["assignments"] = [{"kind": "submission_field", "field_key": "approver"}]
    nodes.append(
        {
            "key": "review",
            "name": "Review",
            "kind": "review",
            "policy": {"mode": "one"},
            "assignments": [{"kind": "user", "target_id": str(review_user)}],
        }
    )
    body["transitions"] = [
        {"source": "start", "target": "review"},
        {"source": "review", "target": "approve"},
        {"source": "approve", "target": "end"},
    ]
    workflow = create_workflow(api, route, body)
    activate(api, route, workflow)
    identifier = draft(api, route, form)
    saved = api.client.put(
        route + f"/submissions/{identifier}",
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "values": {"fields": {"quantity": 1, "approver": str(approver)}},
        },
    )
    assert saved.status_code == 200, saved.text
    submitted = api.client.post(
        route + f"/submissions/{identifier}/submit",
        headers=api.headers("admin"),
        json={
            "expected_revision": 2,
            "idempotency_key": str(uuid7()),
            "reason": "Assigned snapshot",
        },
    )
    assert submitted.status_code == 200, submitted.text
    row = api.client.get(
        route + f"/submissions/{identifier}/workflow", headers=api.headers("admin")
    ).json()["instance"]
    reviewed = action(api, route, row, "reviewer", "review")
    assert reviewed["state"] == "active" and reviewed["current_node"] == "approve"
    assert action(api, route, reviewed, "approver")["state"] == "approved"
    nodes[1]["assignments"] = [{"kind": "manager_of", "field_key": "approver"}]
    denied = api.client.post(
        route + "/workflows",
        headers=api.headers("admin"),
        json={"name": "Unavailable manager", "definition": body},
    )
    assert denied.status_code == 422 and denied.json()["code"] == "manager_relationship_unavailable"


def action(
    api: Api,
    route: str,
    row: dict[str, object],
    subject: str,
    kind: str = "approve",
    key: UUID | None = None,
) -> dict[str, object]:
    result = api.client.post(
        route + f"/workflow-instances/{row['id']}/actions",
        headers=api.headers(subject, subject + "@example.com"),
        json={
            "expected_revision": row["revision"],
            "idempotency_key": str(key or uuid7()),
            "kind": kind,
            "reason": "Verified evidence",
        },
    )
    assert result.status_code == 200, result.text
    return dict(result.json())


def test_assigned_approval_private_draft_immutable_evidence_and_retry(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    user = reviewer(api, org, workspace)
    admin = api.session.scalar(
        select(UserRow).where(UserRow.organization_id == org, UserRow.subject == "admin")
    )
    assert admin
    workflow = create_workflow(api, route, definition(form, [admin.id, user]))
    activate(api, route, workflow)
    private = draft(api, route, form)
    assert (
        api.client.get(
            route + f"/submissions/{private}",
            headers=api.headers("reviewer", "reviewer@example.com"),
        ).status_code
        == 403
    )
    identifier, instance = submit(api, route, form)
    reviewer(api, org, workspace, "unassigned")
    for suffix in (f"/submissions/{identifier}", f"/workflow-instances/{instance['id']}"):
        assert (
            api.client.get(
                route + suffix, headers=api.headers("unassigned", "unassigned@example.com")
            ).status_code
            == 403
        )
    other_workspace = api.workspace(org)
    wrong_scope = f"/api/v1/organizations/{org}/workspaces/{other_workspace}"
    assert (
        api.client.get(
            wrong_scope + f"/workflow-instances/{instance['id']}", headers=api.headers("admin")
        ).status_code
        == 404
    )
    inbox = api.client.get(
        route + "/workflow-inbox", headers=api.headers("reviewer", "reviewer@example.com")
    )
    assert inbox.status_code == 200 and len(inbox.json()["items"]) == 1
    assert (
        api.client.get(
            route + f"/submissions/{identifier}",
            headers=api.headers("reviewer", "reviewer@example.com"),
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            route + f"/workflow-instances/{instance['id']}/actions",
            headers=api.headers("admin"),
            json={
                "expected_revision": instance["revision"],
                "idempotency_key": str(uuid7()),
                "kind": "approve",
                "reason": "Self approval",
            },
        ).status_code
        == 403
    )
    key = uuid7()
    approved = action(api, route, instance, "reviewer", key=key)
    assert approved["state"] == "approved"
    assert action(api, route, instance, "reviewer", key=key) == approved
    assert api.session.scalar(select(func.count()).select_from(ActionRow)) == 1
    assert (
        api.session.scalar(select(SubmissionRow.state).where(SubmissionRow.id == UUID(identifier)))
        == "submitted"
    )
    for sql in (
        "UPDATE workflow_actions SET reason='changed'",
        "DELETE FROM workflow_actions",
        "TRUNCATE workflow_actions",
        "UPDATE workflow_instances SET revision=revision+1",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
    assert api.session.scalar(select(AuditRow).where(AuditRow.type == "workflow.action.approve"))


@pytest.mark.parametrize("mode", ["all", "sequential"])
def test_multiple_approvers_and_live_revocation(api: Api, mode: str) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    first, second = reviewer(api, org, workspace), reviewer(api, org, workspace, "second")
    workflow = create_workflow(api, route, definition(form, [first, second], mode))
    activate(api, route, workflow)
    _, instance = submit(api, route, form)
    if mode == "sequential":
        denied = api.client.post(
            route + f"/workflow-instances/{instance['id']}/actions",
            headers=api.headers("second", "second@example.com"),
            json={
                "expected_revision": instance["revision"],
                "idempotency_key": str(uuid7()),
                "kind": "approve",
                "reason": "Too early",
            },
        )
        assert denied.status_code == 409
    waiting = action(api, route, instance, "reviewer")
    assert waiting["state"] == "active"
    grant = api.session.scalar(
        select(GrantRow).where(GrantRow.organization_id == org, GrantRow.user_id == second)
    )
    assert grant
    response = api.client.post(
        f"/api/v1/organizations/{org}/grants/{grant.id}/revoke", headers=api.headers("admin")
    )
    assert response.status_code in (200, 204), response.text
    assert (
        api.client.get(
            route + "/workflow-inbox", headers=api.headers("second", "second@example.com")
        ).status_code
        == 403
    )
    assert api.session.scalar(select(func.count()).select_from(ActionRow)) == 1


def test_no_independent_approver_rolls_back_submission_start(api: Api) -> None:
    org, _, route, form = setup(api)
    publish(api, route, form)
    admin = api.session.scalar(
        select(UserRow).where(UserRow.organization_id == org, UserRow.subject == "admin")
    )
    assert admin
    workflow = create_workflow(api, route, definition(form, [admin.id]))
    activate(api, route, workflow)
    identifier = draft(api, route, form)
    api.client.put(
        route + f"/submissions/{identifier}",
        headers=api.headers("admin"),
        json={"expected_revision": 1, "values": {"fields": {"quantity": 1}}},
    )
    result = api.client.post(
        route + f"/submissions/{identifier}/submit",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Submit"},
    )
    assert result.status_code == 422, result.text
    api.session.expire_all()
    assert (
        api.session.scalar(select(SubmissionRow.state).where(SubmissionRow.id == UUID(identifier)))
        == "draft"
    )
    assert api.session.scalar(select(func.count()).select_from(InstanceRow)) == 0


def test_return_resubmit_pinned_history_task_approval_amendment_defaults(api: Api) -> None:
    route, schedule, schedule_definition = schedule_setup(api)
    org, workspace = UUID(route.split("/")[4]), UUID(route.split("/")[6])
    form = str(schedule_definition["form_id"])
    user = reviewer(api, org, workspace)
    workflow = create_workflow(api, route, definition(form, [user]))
    activate(api, route, workflow)
    activate_schedule(api, route, schedule)
    generate(api, route, schedule)
    task = api.client.get(route + "/tasks", headers=api.headers("admin")).json()["items"][0]
    claimed = api.client.post(
        route + f"/tasks/{task['id']}/start",
        headers=api.headers("admin"),
        json={"expected_revision": 1},
    )
    assert claimed.status_code == 200, claimed.text
    original = claimed.json()["submission_id"]
    saved = api.client.put(
        route + f"/submissions/{original}",
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "values": {"fields": {"quantity": 5, "acknowledge": "Original acknowledgement"}},
        },
    )
    assert saved.status_code == 200
    result = api.client.post(
        route + f"/submissions/{original}/submit",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Original"},
    )
    assert result.status_code == 200, result.text
    original_payload = result.json()
    instance = api.client.get(
        route + f"/submissions/{original}/workflow", headers=api.headers("admin")
    ).json()["instance"]
    assert (
        api.client.get(route + f"/tasks/{task['id']}", headers=api.headers("admin")).json()["state"]
        == "awaiting_review"
    )
    returned = action(api, route, instance, "reviewer", "return")
    assert returned["state"] == "returned"
    assert (
        api.client.get(route + f"/tasks/{task['id']}", headers=api.headers("admin")).json()["state"]
        == "returned"
    )
    key = str(uuid7())
    revision_url = route + f"/workflow-instances/{returned['id']}/revisions"
    command = {
        "expected_revision": returned["revision"],
        "idempotency_key": key,
        "reason": "Correct quantity",
    }
    revised = api.client.post(revision_url, headers=api.headers("admin"), json=command)
    assert revised.status_code == 201, revised.text
    corrected = revised.json()["id"]
    assert corrected != original and revised.json()["signatures"] == []
    assert not revised.json()["values"]["fields"].get("acknowledge")
    replay = api.client.post(revision_url, headers=api.headers("admin"), json=command)
    assert replay.status_code == 201 and replay.json()["id"] == corrected
    assert (
        api.client.get(
            route + f"/submissions/{corrected}",
            headers=api.headers("reviewer", "reviewer@example.com"),
        ).status_code
        == 403
    )
    clone = api.client.post(
        route + f"/workflows/{workflow}/versions",
        headers=api.headers("admin"),
        json={"source_number": 1, "number": 2},
    )
    assert clone.status_code == 201
    activate(api, route, workflow, 2)
    saved = api.client.put(
        route + f"/submissions/{corrected}",
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "values": {"fields": {"quantity": 6, "acknowledge": "Corrected acknowledgement"}},
        },
    )
    assert saved.status_code == 200, saved.text
    result = api.client.post(
        route + f"/submissions/{corrected}/submit",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Resubmit"},
    )
    assert result.status_code == 200, result.text
    corrected_history = api.client.get(
        route + f"/submissions/{corrected}/workflow", headers=api.headers("admin")
    ).json()
    assert corrected_history["instance"]["workflow_number"] == 1
    assert corrected_history["parent"]["root_submission_id"] == original
    approved = action(api, route, corrected_history["instance"], "reviewer")
    assert approved["state"] == "approved"
    task_result = api.client.get(
        route + f"/tasks/{task['id']}", headers=api.headers("admin")
    ).json()
    assert task_result["state"] == "approved" and task_result["submission_id"] == original
    assert (
        api.client.get(route + f"/submissions/{original}", headers=api.headers("admin")).json()
        == original_payload
    )
    assert (
        api.client.get(
            route + f"/workflow-instances/{returned['id']}", headers=api.headers("admin")
        ).json()["instance"]["state"]
        == "returned"
    )
    owner = UUID(original_payload["owner_id"])
    defaults = compose(api.session).forms.default_context
    assert defaults
    assert defaults.previous_approved(org, workspace, UUID(form), owner, "quantity") == 6
    assert defaults.previous_approved(org, workspace, UUID(form), uuid7(), "quantity") is None
    assert defaults.previous_approved(uuid7(), workspace, UUID(form), owner, "quantity") is None
    amendment = api.client.post(
        route + f"/workflow-instances/{approved['id']}/revisions",
        headers=api.headers("admin"),
        json={
            "expected_revision": approved["revision"],
            "idempotency_key": str(uuid7()),
            "reason": "Governed amendment",
        },
    )
    assert amendment.status_code == 201 and amendment.json()["id"] != corrected
    assert defaults.previous_approved(org, workspace, UUID(form), owner, "quantity") == 6
    for sql in (
        "DELETE FROM workflow_revisions",
        "TRUNCATE workflow_revisions",
        "UPDATE workflow_revisions SET reason='changed'",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
