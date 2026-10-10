from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.reporting.application.datasets import ReportingService
from operations.modules.scheduling.application.contracts import Assignment
from operations.modules.tasks.application.contracts import Task
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase4_api import activate, generate, schedule_setup


@pytest.mark.integration
def test_overdue_dataset_is_bounded_and_personal_scope_is_preserved(api: Api) -> None:
    route, schedule, _ = schedule_setup(api)
    activate(api, route, schedule)
    assert generate(api, route, schedule)["created"] == 1

    response = api.client.get(route + "/reports/overdue-tasks", headers=api.headers("admin"))
    assert response.status_code == 200, response.text
    page = response.json()
    assert len(page["items"]) == 1
    assert set(page["items"][0]) == {"id", "project_id", "kind", "name", "state", "due_at"}
    assert page["items"][0]["state"] == "open"
    assert page["next_cursor"] is None

    org, workspace = route.split("/organizations/")[1].split("/workspaces/")
    token = api.invitation(UUID(org), UUID(workspace), role="Viewer")
    api.accept(UUID(org), token)
    viewer = api.client.get(route + "/reports/overdue-tasks", headers=api.headers("invitee"))
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["items"] == []


def test_overdue_dataset_uses_task_query_and_returns_minimal_projection() -> None:
    organization, workspace, user, identifier = uuid7(), uuid7(), uuid7(), uuid7()
    now = datetime.now(UTC)
    task = Task(
        id=identifier,
        organization_id=organization,
        workspace_id=workspace,
        project_id=None,
        kind="generic",
        origin_id=uuid7(),
        name="Check instrument",
        timezone="UTC",
        occurs_at=now,
        due_at=now,
        assignment=Assignment(kind="user", target_id=user),
        assignment_key="user:" + str(user),
        recipient_ids=[user],
        reminder_offsets=[],
        state="open",
    )
    cursor = uuid7()

    class Tasks:
        def inbox(
            self,
            actor: RequestContext,
            org: UUID,
            selected_workspace: UUID,
            project: UUID | None,
            view: str,
            mode: str,
            target: UUID | None,
            after: UUID | None,
        ) -> tuple[list[Task], UUID | None]:
            assert actor.principal.subject == "reporter"
            assert (org, selected_workspace, project) == (organization, workspace, None)
            assert (view, mode, target, after) == ("overdue", "personal", None, cursor)
            return [task], cursor

    result = ReportingService(Tasks()).overdue_tasks(
        RequestContext(Principal("issuer", "reporter"), uuid7(), uuid7()),
        organization,
        workspace,
        None,
        cursor,
    )
    assert result.next_cursor == cursor
    assert result.items[0].id == identifier
    assert result.items[0].name == "Check instrument"
