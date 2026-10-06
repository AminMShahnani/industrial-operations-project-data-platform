from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from operations.modules.identity.infrastructure.persistence import UserRow
from operations.modules.tasks.infrastructure.persistence import TaskRow
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import publish, setup

pytestmark = pytest.mark.integration


def schedule_setup(api: Api, at: datetime | None = None) -> tuple[str, str, dict[str, object]]:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    user = api.session.scalar(
        select(UserRow).where(UserRow.organization_id == org, UserRow.subject == "admin")
    )
    assert user
    definition: dict[str, object] = {
        "form_id": form,
        "form_number": 1,
        "recurrence": {
            "kind": "one_time",
            "at": (at or datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
        "assignments": [{"kind": "user", "target_id": str(user.id)}],
        "due_after_seconds": 0,
        "reminder_offsets": [0],
    }
    response = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"name": "Shared operational work", "definition": definition},
    )
    assert response.status_code == 201, response.text
    return route, str(response.json()["id"]), definition


def activate(api: Api, route: str, identifier: str, number: int = 1) -> None:
    url = route + f"/schedules/{identifier}/versions/{number}/activate"
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


def generate(api: Api, route: str, identifier: str) -> dict[str, object]:
    now = datetime.now(UTC)
    response = api.client.post(
        route + f"/schedules/{identifier}/materialize",
        headers=api.headers("admin"),
        json={
            "start": (now - timedelta(days=1)).isoformat(),
            "end": (now + timedelta(days=2)).isoformat(),
            "dry_run": False,
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_exact_version_idempotent_materialization_claim_submission_audit(api: Api) -> None:
    route, identifier, _ = schedule_setup(api)
    activate(api, route, identifier)
    assert generate(api, route, identifier)["created"] == 1
    assert generate(api, route, identifier)["created"] == 0
    tasks = api.client.get(route + "/tasks?view=overdue", headers=api.headers("admin")).json()[
        "items"
    ]
    assert len(tasks) == 1
    task = tasks[0]
    start = route + f"/tasks/{task['id']}/start"
    claimed = api.client.post(start, headers=api.headers("admin"), json={"expected_revision": 1})
    assert claimed.status_code == 200, claimed.text
    submission = claimed.json()["submission_id"]
    replay = api.client.post(start, headers=api.headers("admin"), json={"expected_revision": 1})
    assert replay.status_code == 200 and replay.json()["submission_id"] == submission
    saved = api.client.put(
        route + f"/submissions/{submission}",
        headers=api.headers("admin"),
        json={"expected_revision": 1, "values": {"fields": {"quantity": 3}}},
    )
    assert saved.status_code == 200, saved.text
    submit = api.client.post(
        route + f"/submissions/{submission}/submit",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Task complete"},
    )
    assert submit.status_code == 200, submit.text
    current = api.client.get(route + f"/tasks/{task['id']}", headers=api.headers("admin")).json()
    assert (
        current["state"] == "submitted"
        and current["form_version_id"] == submit.json()["form_version_id"]
    )
    assert (
        api.session.scalar(text("SELECT count(*) FROM audit_events WHERE type='task.submitted'"))
        == 1
    )


def test_activation_immutability_stale_revision_and_guarded_rollback(api: Api) -> None:
    route, identifier, definition = schedule_setup(api)
    url = route + f"/schedules/{identifier}/versions/1"
    assert (
        api.client.post(
            url + "/activate",
            headers=api.headers("admin"),
            json={"expected_revision": 1, "dry_run": False},
        ).status_code
        == 409
    )
    activate(api, route, identifier)
    assert (
        api.client.put(
            url,
            headers=api.headers("admin"),
            json={"expected_revision": 2, "definition": definition},
        ).status_code
        == 409
    )

    for sql in (
        "UPDATE schedule_versions SET definition='{}',revision=revision+1",
        "DELETE FROM schedules",
        "TRUNCATE schedule_versions CASCADE",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("b71acf0449b2")
    assert revision
    migration = revision.module
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        migration.downgrade()


def test_group_claim_peer_privacy_revocation_and_cancellation(api: Api) -> None:
    route, identifier, definition = schedule_setup(api)
    org = UUID(route.split("/")[4])
    workspace = UUID(route.split("/")[6])
    token = api.invitation(org, workspace, "Contributor")
    member = api.accept(org, token)
    group = api.client.post(
        route + "/groups", headers=api.headers("admin"), json={"name": "Team", "kind": "team"}
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    peer = api.accept(
        org,
        api.invitation(org, workspace, "Contributor", email="peer@example.com"),
        "peer",
        "peer@example.com",
    )
    for user in [member, peer]:
        result = api.client.post(
            route + f"/groups/{group_id}/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(user)},
        )
        assert result.status_code == 201, result.text
        if user == peer:
            peer_membership = result.json()["id"]
    definition["assignments"] = [{"kind": "team", "target_id": group_id}]
    saved = api.client.put(
        route + f"/schedules/{identifier}/versions/1",
        headers=api.headers("admin"),
        json={"expected_revision": 1, "definition": definition},
    )
    assert saved.status_code == 200, saved.text
    preview = api.client.post(
        route + f"/schedules/{identifier}/versions/1/activate",
        headers=api.headers("admin"),
        json={"expected_revision": 2},
    ).json()
    activated = api.client.post(
        route + f"/schedules/{identifier}/versions/1/activate",
        headers=api.headers("admin"),
        json={
            "expected_revision": 2,
            "dry_run": False,
            "expected_sha256": preview["content_sha256"],
        },
    )
    assert activated.status_code == 200, activated.text
    generate(api, route, identifier)
    task = api.client.get(route + "/tasks?mode=project", headers=api.headers("admin")).json()[
        "items"
    ][0]
    claimed = api.client.post(
        route + f"/tasks/{task['id']}/start",
        headers=api.headers("invitee", "invitee@example.com"),
        json={"expected_revision": 1},
    )
    assert claimed.status_code == 200, claimed.text
    assert (
        api.client.post(
            route + f"/tasks/{task['id']}/start",
            headers=api.headers("peer", "peer@example.com"),
            json={"expected_revision": 1},
        ).status_code
        == 409
    )
    assert (
        api.client.get(
            route + f"/submissions/{claimed.json()['submission_id']}", headers=api.headers("admin")
        ).status_code
        == 403
    )
    cancel = api.client.post(
        route + f"/tasks/{task['id']}/cancel",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "reason": "No longer required", "dry_run": False},
    )
    removed = api.client.post(
        route + f"/groups/{group_id}/memberships/{peer_membership}/revoke",
        headers=api.headers("admin"),
    )
    assert removed.status_code == 204, removed.text
    assert (
        api.client.post(
            route + f"/tasks/{task['id']}/start",
            headers=api.headers("peer", "peer@example.com"),
            json={"expected_revision": 1},
        ).status_code
        == 403
    )
    assert cancel.status_code == 200, cancel.text
    assert (
        api.client.put(
            route + f"/submissions/{claimed.json()['submission_id']}",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"expected_revision": 1, "values": {"fields": {"quantity": 1}}},
        ).status_code
        == 409
    )

    revoked = api.client.post(
        f"/api/v1/organizations/{org}/users/{member}/revoke", headers=api.headers("admin")
    )
    assert revoked.status_code == 204, revoked.text
    assert (
        api.client.get(
            route + f"/tasks/{task['id']}", headers=api.headers("invitee", "invitee@example.com")
        ).status_code
        == 403
    )


def test_reminders_pausing_and_future_supersession_preserve_claims(api: Api) -> None:
    route, identifier, _ = schedule_setup(api)
    activate(api, route, identifier)
    generate(api, route, identifier)
    result = api.client.post(
        route + "/task-reminders/generate", headers=api.headers("admin"), json={}
    )
    assert result.status_code == 200 and result.json()["created"] == 1, result.text
    assert (
        api.client.post(
            route + "/task-reminders/generate", headers=api.headers("admin"), json={}
        ).json()["created"]
        == 0
    )
    lifecycle = api.client.post(
        route + f"/schedules/{identifier}/versions/1/lifecycle",
        headers=api.headers("admin"),
        json={"expected_revision": 2, "state": "paused", "reason": "Pause", "dry_run": False},
    )
    assert lifecycle.status_code == 200, lifecycle.text
    now = datetime.now(UTC)
    assert (
        api.client.post(
            route + f"/schedules/{identifier}/materialize",
            headers=api.headers("admin"),
            json={
                "start": now.isoformat(),
                "end": (now + timedelta(days=1)).isoformat(),
                "dry_run": False,
            },
        ).status_code
        == 409
    )
    route2, identifier2, _ = schedule_setup(api, datetime.now(UTC) + timedelta(days=1))
    activate(api, route2, identifier2)
    generate(api, route2, identifier2)
    clone = api.client.post(
        route2 + f"/schedules/{identifier2}/versions",
        headers=api.headers("admin"),
        json={"source_number": 1, "number": 2},
    )
    assert clone.status_code == 201, clone.text
    activate(api, route2, identifier2, 2)
    assert (
        api.client.get(route2 + "/tasks", headers=api.headers("admin")).json()["items"][0]["state"]
        == "superseded"
    )


def test_cross_tenant_viewer_and_invalid_targets_reject(api: Api) -> None:
    route, identifier, definition = schedule_setup(api)
    org = UUID(route.split("/")[4])
    workspace = UUID(route.split("/")[6])
    token = api.invitation(org, workspace)
    api.accept(org, token)
    assert (
        api.client.post(
            route + "/schedules",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"name": "Denied", "definition": definition},
        ).status_code
        == 403
    )
    assert (
        api.client.get(
            route + f"/schedules/{identifier}/versions/1", headers=api.headers()
        ).status_code
        == 403
    )
    definition["assignments"] = [{"kind": "user", "target_id": str(uuid7())}]
    response = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"name": "Invalid", "definition": definition},
    )
    assert response.status_code == 422, response.text
    activate(api, route, identifier)
    generate(api, route, identifier)
    task = api.client.get(route + "/tasks", headers=api.headers("admin")).json()["items"][0]
    assert (
        api.client.get(
            route + f"/tasks/{task['id']}", headers=api.headers("invitee", "invitee@example.com")
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            route + f"/tasks/{task['id']}/start",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"expected_revision": 1},
        ).status_code
        == 403
    )
    with pytest.raises(DBAPIError), api.session.begin_nested():
        api.session.execute(
            text("UPDATE task_occurrences SET recipient_ids='[]',revision=revision+1")
        )
    assert api.session.scalar(select(TaskRow.id))


def test_shift_defaults_and_relative_event_idempotency(api: Api) -> None:
    route, identifier, definition = schedule_setup(api)
    org = UUID(route.split("/")[4])
    workspace = UUID(route.split("/")[6])
    user = api.session.scalar(
        select(UserRow).where(UserRow.organization_id == org, UserRow.subject == "admin")
    )
    assert user
    now = datetime.now(UTC)
    shift = api.client.post(
        route + "/shifts",
        headers=api.headers("admin"),
        json={
            "code": "day",
            "number": 1,
            "name": "Day shift",
            "timezone": "UTC",
            "starts_at": (now - timedelta(hours=1)).strftime("%H:%M:%S"),
            "duration_seconds": 7200,
            "user_ids": [str(user.id)],
        },
    )
    assert shift.status_code == 201, shift.text
    from operations.composition import compose
    from operations.modules.identity.application.contracts import Principal

    services = compose(api.session, Principal(user.issuer, user.subject))
    assert services.forms.default_context
    assert services.forms.default_context.shift(org, workspace, None, user.id) == shift.json()["id"]
    assert (
        services.forms.default_context.previous_approved(org, workspace, uuid7(), user.id, "field")
        is None
    )
    definition["recurrence"] = {
        "kind": "shift",
        "timezone": "UTC",
        "starts_local": (now - timedelta(days=1)).replace(tzinfo=None).isoformat(),
        "shift_id": shift.json()["id"],
    }
    saved = api.client.put(
        route + f"/schedules/{identifier}/versions/1",
        headers=api.headers("admin"),
        json={"expected_revision": 1, "definition": definition},
    )
    assert saved.status_code == 200, saved.text
    plan = api.client.post(
        route + f"/schedules/{identifier}/versions/1/activate",
        headers=api.headers("admin"),
        json={"expected_revision": 2},
    )
    assert plan.status_code == 200, plan.text
    response = api.client.post(
        route + "/schedule-triggers",
        headers=api.headers("admin"),
        json={
            "idempotency_key": str(uuid7()),
            "code": "operational.event",
            "occurred_at": now.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    event = response.json()
    event_command = {
        "idempotency_key": event["id"],
        "code": event["code"],
        "occurred_at": event["occurred_at"],
    }
    assert (
        api.client.post(
            route + "/schedule-triggers", headers=api.headers("admin"), json=event_command
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            route + "/schedule-triggers",
            headers=api.headers("admin"),
            json=event_command | {"occurred_at": (now + timedelta(hours=1)).isoformat()},
        ).status_code
        == 409
    )
    definition["recurrence"] = {
        "kind": "relative_event",
        "event_code": "operational.event",
        "offset_seconds": 3600,
    }
    created = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"name": "Event work", "definition": definition},
    )
    assert created.status_code == 201, created.text
    event_schedule = str(created.json()["id"])
    activate(api, route, event_schedule)
    assert generate(api, route, event_schedule)["created"] == 1
    assert generate(api, route, event_schedule)["created"] == 0


def test_project_milestone_and_no_implicit_project_execution(api: Api) -> None:
    route, _, definition = schedule_setup(api)
    project = api.client.post(
        route + "/projects", headers=api.headers("admin"), json={"name": "Milestone project"}
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    milestone = api.client.post(
        route + "/milestones",
        headers=api.headers("admin"),
        json={
            "project_id": project_id,
            "name": "Operational milestone",
            "planned_at": datetime.now(UTC).isoformat(),
        },
    )
    assert milestone.status_code == 201, milestone.text
    form = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={
            "name": "Project report",
            "project_id": project_id,
            "definition": {
                "sections": [
                    {
                        "key": "main",
                        "label": "Main",
                        "components": [{"key": "note", "kind": "text", "label": "Note"}],
                    }
                ]
            },
        },
    )
    assert form.status_code == 201, form.text
    publish(api, route, form.json()["id"])
    org = UUID(route.split("/")[4])
    workspace = UUID(route.split("/")[6])
    member = api.accept(org, api.invitation(org, workspace, "Contributor"))
    definition["form_id"] = form.json()["id"]
    definition["recurrence"] = {"kind": "milestone", "milestone_id": milestone.json()["id"]}
    definition["assignments"] = [{"kind": "user", "target_id": str(member)}]
    response = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"project_id": project_id, "name": "Cannot grant access", "definition": definition},
    )
    assert response.status_code == 422, response.text
    definition["assignments"] = [{"kind": "role", "role": "ProjectManager"}]
    response = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"project_id": project_id, "name": "Milestone work", "definition": definition},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    activate(api, route, identifier)
    assert generate(api, route, identifier)["created"] == 1
    assert (
        api.client.get(
            route + f"/tasks?project_id={project_id}",
            headers=api.headers("invitee", "invitee@example.com"),
        ).status_code
        == 403
    )


def test_cursor_paging_and_window_bounds(api: Api) -> None:
    route, _, definition = schedule_setup(api)
    now = datetime.now(UTC)
    definition["recurrence"] = {
        "kind": "interval",
        "at": (now - timedelta(hours=120)).isoformat(),
        "interval_seconds": 3600,
    }
    response = api.client.post(
        route + "/schedules",
        headers=api.headers("admin"),
        json={"name": "Paged work", "definition": definition},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    activate(api, route, identifier)
    body = {
        "start": (now - timedelta(hours=120)).isoformat(),
        "end": now.isoformat(),
        "dry_run": False,
    }
    generated = api.client.post(
        route + f"/schedules/{identifier}/materialize", headers=api.headers("admin"), json=body
    )
    assert generated.status_code == 200 and generated.json()["created"] == 120, generated.text
    first = api.client.get(route + "/tasks", headers=api.headers("admin")).json()
    second = api.client.get(
        route + "/tasks?cursor=" + first["next_cursor"], headers=api.headers("admin")
    ).json()
    assert len(first["items"]) == 100 and len(second["items"]) == 20
    assert not {x["id"] for x in first["items"]} & {x["id"] for x in second["items"]}
    body["end"] = (now + timedelta(days=61)).isoformat()
    assert (
        api.client.post(
            route + f"/schedules/{identifier}/materialize", headers=api.headers("admin"), json=body
        ).status_code
        == 422
    )
