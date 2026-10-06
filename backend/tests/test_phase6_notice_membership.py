from uuid import UUID

import pytest
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.notifications.infrastructure.persistence import AttemptRow, NoticeRow
from operations.worker import process_notifications
from sqlalchemy import func, select
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase3_api import publish, setup
from test_phase5_api import activate, create_workflow, reviewer, submit
from test_phase6_actions import context
from test_phase6_automatic_notices import dispatch
from test_phase6_periodic import task_fixture

pytestmark = pytest.mark.integration


def test_notify_group_snapshot_excludes_new_members_and_rechecks_departed_members(api: Api) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    original = reviewer(api, org, workspace)
    newcomer = reviewer(api, org, workspace, subject="newcomer")
    response = api.client.post(
        route + "/groups",
        headers=api.headers("admin"),
        json={"name": "Notification team", "kind": "team"},
    )
    assert response.status_code == 201
    group = str(response.json()["id"])
    membership = api.client.post(
        route + f"/groups/{group}/memberships",
        headers=api.headers("admin"),
        json={"user_id": str(original)},
    )
    assert membership.status_code == 201
    original_membership = str(membership.json()["id"])
    workflow = create_workflow(
        api,
        route,
        {
            "form_id": form,
            "form_number": 1,
            "nodes": [
                {"key": "start", "name": "Start", "kind": "start"},
                {
                    "key": "notify",
                    "name": "Notify",
                    "kind": "notify",
                    "assignments": [{"kind": "team", "target_id": group}],
                },
                {"key": "end", "name": "End", "kind": "end"},
            ],
            "transitions": [
                {"source": "start", "target": "notify"},
                {"source": "notify", "target": "end"},
            ],
        },
    )
    activate(api, route, workflow)
    _, instance = submit(api, route, form)
    assert (
        api.client.post(
            route + f"/groups/{group}/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(newcomer)},
        ).status_code
        == 201
    )
    message = dispatch(api, org, "workflow.notification.requested")
    assert process_notifications(api.session, message).state == "completed"
    services = compose(api.session)
    actor, _ = context(api, org)
    recipient = services.identity.active_context(org, original, actor)
    new_recipient = services.identity.active_context(org, newcomer, actor)
    items, _ = services.notifications.inbox(recipient, org, workspace)
    assert len(items) == 1
    assert services.notifications.inbox(new_recipient, org, workspace)[0] == []
    with pytest.raises(ServiceError):
        services.workflow_runtime.notification_access(
            new_recipient,
            org,
            workspace,
            UUID(str(instance["id"])),
            items[0].notice.source_intent_id or UUID(int=0),
        )
    result = api.client.post(
        route + f"/groups/{group}/memberships/{original_membership}/revoke",
        headers=api.headers("admin"),
        json={"reason": "Reassignment"},
    )
    assert result.status_code == 204, result.text
    assert services.notifications.inbox(recipient, org, workspace)[0] == []
    with pytest.raises(ServiceError):
        services.notifications.mark_read(recipient, org, items[0].notice.id)
    assert api.session.scalar(select(func.count()).select_from(NoticeRow)) == 1


def test_cancelled_task_source_is_skipped_without_work_or_source_state_changes(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    services.tasks.cancel(actor, org, workspace, task.id, 1, "Cancelled before delivery", False)
    message = dispatch(api, org, "task.created")
    assert process_notifications(api.session, message).state == "completed"
    attempt = api.session.scalar(select(AttemptRow))
    assert attempt and attempt.created == 0 and attempt.skipped == 1
    assert services.notifications.inbox(actor, org, workspace)[0] == []
    assert services.tasks.access(actor, org, workspace, task.id).state == "cancelled"
