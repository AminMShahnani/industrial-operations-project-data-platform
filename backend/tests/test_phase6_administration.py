from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.contracts import RuleDefinition
from operations.modules.automation.application.events import (
    DeliveryMessage,
    EventContext,
    OperationalEvent,
)
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import DeliveryRow, RunRow
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.worker import process_automation
from sqlalchemy import func, select, update
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase6_actions import context

pytestmark = pytest.mark.integration

DEFINITION = {
    "trigger": "project.phase.changed",
    "actions": [{"kind": "set_metadata", "description": "Reviewed phase change"}],
}


def fixture(api: Api) -> tuple[UUID, UUID, UUID, str, str]:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = UUID(project(api, org, workspace))
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}/automation-rules"
    result = api.client.post(
        route,
        headers=api.headers("admin"),
        json={
            "name": "Phase notice",
            "project_id": str(identifier),
            "definition": DEFINITION,
        },
    )
    assert result.status_code == 201, result.text
    return org, workspace, identifier, route, str(result.json()["id"])


def active_run(api: Api) -> tuple[UUID, UUID, str, str, UUID, DeliveryMessage]:
    org, workspace, identifier, route, rule = fixture(api)
    activation = route + f"/{rule}/versions/1/activate"
    preview = api.client.post(
        activation, headers=api.headers("admin"), json={"expected_revision": 1}
    )
    assert preview.status_code == 200, preview.text
    result = api.client.post(
        activation,
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "dry_run": False,
            "expected_sha256": preview.json()["content_sha256"],
        },
    )
    assert result.status_code == 200, result.text
    actor, _ = context(api, org)
    compose(api.session).projects.transition(
        actor, org, workspace, identifier, "active", 1, "Start"
    )
    runs = api.client.get(route + f"/{rule}/versions/1/runs", headers=api.headers("admin"))
    assert runs.status_code == 200 and len(runs.json()["items"]) == 1
    run = runs.json()["items"][0]
    return (
        org,
        workspace,
        route,
        rule,
        UUID(run["id"]),
        DeliveryMessage(
            organization_id=org,
            delivery_id=delivery_id(UUID(run["event_id"]), "automation"),
        ),
    )


def test_definition_preview_immutability_clone_retire_and_conflicts(api: Api) -> None:
    _, _, _, route, rule = fixture(api)
    version = route + f"/{rule}/versions/1"
    headers = api.headers("admin")
    count = api.session.scalar(select(func.count()).select_from(AuditRow))
    preview = api.client.post(version + "/activate", headers=headers, json={"expected_revision": 1})
    assert preview.status_code == 200 and preview.json()["state"] == "draft"
    assert api.session.scalar(select(func.count()).select_from(AuditRow)) == count
    assert (
        api.client.post(
            version + "/activate",
            headers=headers,
            json={
                "expected_revision": 1,
                "dry_run": False,
                "expected_sha256": "0" * 64,
            },
        ).status_code
        == 409
    )
    saved = api.client.put(
        version, headers=headers, json={"expected_revision": 1, "definition": DEFINITION}
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert (
        api.client.post(
            version + "/activate",
            headers=headers,
            json={
                "expected_revision": 1,
                "dry_run": False,
                "expected_sha256": preview.json()["content_sha256"],
            },
        ).status_code
        == 409
    )
    preview = api.client.post(version + "/activate", headers=headers, json={"expected_revision": 2})
    assert (
        api.client.post(
            version + "/activate",
            headers=headers,
            json={
                "expected_revision": 2,
                "dry_run": False,
                "expected_sha256": preview.json()["content_sha256"],
            },
        ).status_code
        == 200
    )
    assert (
        api.client.put(
            version, headers=headers, json={"expected_revision": 3, "definition": DEFINITION}
        ).status_code
        == 409
    )
    cloned = api.client.post(
        route + f"/{rule}/versions", headers=headers, json={"source_number": 1, "number": 2}
    )
    assert cloned.status_code == 201 and cloned.json()["state"] == "draft"
    assert (
        api.client.post(
            route + f"/{rule}/versions", headers=headers, json={"source_number": 1, "number": 2}
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            route + f"/{rule}/retire",
            headers=headers,
            json={"expected_revision": 1, "reason": "stop"},
        ).status_code
        == 409
    )
    retired = api.client.post(
        route + f"/{rule}/retire",
        headers=headers,
        json={"expected_revision": 2, "reason": " stop "},
    )
    assert retired.status_code == 200 and retired.json()["active_number"] is None
    assert api.client.get(version, headers=headers).json()["state"] == "retired"
    assert api.client.get(route + f"/{rule}/versions/2", headers=headers).json()["state"] == "draft"


def test_scoped_lists_draft_privacy_and_evidence_binding(api: Api) -> None:
    org, workspace, route, rule, run, message = active_run(api)
    token = api.invitation(org, workspace)
    api.accept(org, token)
    headers = api.headers("invitee", "invitee@example.com")
    for suffix in (
        "",
        f"/{rule}",
        f"/{rule}/versions",
        f"/{rule}/versions/1",
        f"/{rule}/versions/1/runs",
        f"/{rule}/runs/{run}",
    ):
        assert api.client.get(route + suffix, headers=headers).status_code == 403
    assert api.client.get(route, headers=api.headers("admin")).json()["items"] == []
    identifier = api.session.scalar(select(RunRow).where(RunRow.id == run))
    assert identifier
    version = compose(api.session).automation.store.version_by_id(org, identifier.rule_version_id)
    assert version
    owner = compose(api.session).automation.store.rule(org, workspace, UUID(rule))
    assert owner
    assert (
        len(
            api.client.get(
                route, headers=api.headers("admin"), params={"project_id": str(owner.project_id)}
            ).json()["items"]
        )
        == 1
    )
    other_workspace = api.workspace(org)
    wrong = route.replace(str(workspace), str(other_workspace))
    assert api.client.get(wrong + f"/{rule}", headers=api.headers("admin")).status_code == 404
    foreign = api.organization("other")
    assert (
        api.client.get(
            route.replace(str(org), str(foreign)) + f"/{rule}", headers=api.headers("other")
        ).status_code
        == 404
    )
    other_project = UUID(project(api, org, workspace))
    actor, _ = context(api, org)
    other = compose(api.session).automation.create(
        actor, org, workspace, other_project, "Other", RuleDefinition.model_validate(DEFINITION)
    )
    assert (
        api.client.get(route + f"/{other.id}/runs/{run}", headers=api.headers("admin")).status_code
        == 404
    )
    assert process_automation(api.session, message).state == "completed"
    history = api.client.get(route + f"/{rule}/runs/{run}", headers=api.headers("admin"))
    assert history.status_code == 200
    assert len(history.json()["attempts"]) == len(history.json()["receipts"]) == 1
    assert set(history.json()) == {"run", "attempts", "receipts"}
    assert "Reviewed phase change" not in history.text and "payload" not in history.text


def test_replay_review_preserves_evidence_and_rejects_duplicate(api: Api) -> None:
    org, workspace, route, rule, run, message = active_run(api)
    service = compose(api.session).automation
    service.failed(org, run, "fixture_adapter_error", False)
    endpoint = route + f"/{rule}/runs/{run}/replay"
    headers = api.headers("admin")
    before = service.store.attempts(org, run)
    count = api.session.scalar(select(func.count()).select_from(AuditRow))
    preview = api.client.post(endpoint, headers=headers, json={})
    assert preview.status_code == 200 and not preview.json()["applied"]
    assert api.session.scalar(select(func.count()).select_from(AuditRow)) == count
    digest = preview.json()["review_sha256"]
    assert (
        api.client.post(
            endpoint, headers=headers, json={"dry_run": False, "reason": "repair"}
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            endpoint, headers=headers, json={"dry_run": False, "review_sha256": digest}
        ).status_code
        == 422
    )
    body = {"dry_run": False, "review_sha256": digest, "reason": " Repair confirmed "}
    result = api.client.post(endpoint, headers=headers, json=body)
    assert (
        result.status_code == 200
        and result.json()["applied"]
        and result.json()["run"]["attempts"] == 1
    )
    assert api.client.post(endpoint, headers=headers, json=body).status_code == 409
    assert service.store.attempts(org, run) == before
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.aggregate_id == run, AuditRow.type == "automation.run.replayed"
        )
    )
    assert audit and audit.payload["reason"] == "Repair confirmed"
    assert process_automation(api.session, message).state == "completed"
    history = service.history(context(api, org)[0], org, workspace, UUID(rule), run)
    assert len(history.attempts) == 2 and len(history.receipts) == 1
    assert api.client.post(endpoint, headers=headers, json={}).status_code == 409


def test_replay_delivery_progress_and_revoked_delegation(api: Api) -> None:
    org, _, route, rule, run, message = active_run(api)
    service = compose(api.session).automation
    service.failed(org, run, "fixture_error", False)
    endpoint = route + f"/{rule}/runs/{run}/replay"
    preview = api.client.post(endpoint, headers=api.headers("admin"), json={}).json()
    api.session.execute(
        update(DeliveryRow).where(DeliveryRow.id == message.delivery_id).values(state="dispatched")
    )
    assert (
        api.client.post(
            endpoint,
            headers=api.headers("admin"),
            json={
                "dry_run": False,
                "review_sha256": preview["review_sha256"],
                "reason": "repair",
            },
        ).status_code
        == 409
    )
    _, admin = context(api, org)
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == admin)
        .values(revoked=True)
    )
    assert api.client.post(endpoint, headers=api.headers("admin"), json={}).status_code == 403


def test_replay_attempt_cap_and_invalid_contracts(api: Api) -> None:
    org, _, route, rule, run, _ = active_run(api)
    service = compose(api.session).automation
    actor, _ = context(api, org)
    workspace = service.store.run(org, run)
    assert workspace
    for number in range(20):
        service.failed(org, run, "fixture_error", False)
        if number < 19:
            service.replay(actor, org, workspace.workspace_id, run, "Bounded recovery")
    result = api.client.post(
        route + f"/{rule}/runs/{run}/replay", headers=api.headers("admin"), json={}
    )
    assert result.status_code == 409 and result.json()["code"] == "automation_attempt_limit"
    for definition in (
        {"trigger": "project.phase.changed", "actions": [{"kind": "python", "code": "print(1)"}]},
        {"trigger": "project.phase.changed", "actions": [], "unexpected": True},
    ):
        assert (
            api.client.post(
                route,
                headers=api.headers("admin"),
                json={"name": "Unsafe", "definition": definition},
            ).status_code
            == 422
        )
    final = service.store.run(org, run)
    assert final and final.attempts == 20


def test_rule_pagination_filters_scope_before_limit(api: Api) -> None:
    org, workspace, identifier, route, rule = fixture(api)
    actor, _ = context(api, org)
    service = compose(api.session).automation
    for _ in range(103):
        service.create(
            actor, org, workspace, identifier, "Paged", RuleDefinition.model_validate(DEFINITION)
        )
    # Distractor scope must never enter a project page or consume its bound.
    service.create(
        actor,
        org,
        workspace,
        None,
        "Workspace",
        RuleDefinition.model_validate(
            {
                "trigger": "task.created",
                "actions": [{"kind": "notify", "recipients": [str(context(api, org)[1])]}],
            }
        ),
    )
    first = api.client.get(
        route, headers=api.headers("admin"), params={"project_id": str(identifier)}
    ).json()
    second = api.client.get(
        route,
        headers=api.headers("admin"),
        params={"project_id": str(identifier), "cursor": first["next_cursor"]},
    ).json()
    assert (
        len(first["items"]) == 100 and len(second["items"]) == 4 and second["next_cursor"] is None
    )
    ids = [row["id"] for row in first["items"] + second["items"]]
    assert len(set(ids)) == 104 and rule in ids


def test_workspace_manager_can_edit_but_cannot_activate(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    token = api.invitation(org, workspace, "WorkspaceAdmin")
    api.accept(org, token)
    _, admin = context(api, org)
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}/automation-rules"
    headers = api.headers("invitee", "invitee@example.com")
    result = api.client.post(
        route,
        headers=headers,
        json={
            "name": "Workspace rule",
            "definition": {
                "trigger": "task.created",
                "actions": [{"kind": "notify", "recipients": [str(admin)]}],
            },
        },
    )
    assert result.status_code == 201, result.text
    rule = result.json()["id"]
    assert api.client.get(route + f"/{rule}/versions", headers=headers).status_code == 200
    assert (
        api.client.post(
            route + f"/{rule}/versions/1/activate", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 403
    )
    assert api.client.get(route + f"/{rule}/versions/1", headers=headers).json()["state"] == "draft"


def test_version_and_run_pages_are_exact_and_bounded(api: Api) -> None:
    org, workspace, route, rule, run, _ = active_run(api)
    service = compose(api.session).automation
    actor, _ = context(api, org)
    for number in range(2, 105):
        service.clone(actor, org, workspace, UUID(rule), 1, number)
    headers = api.headers("admin")
    first = api.client.get(route + f"/{rule}/versions", headers=headers).json()
    second = api.client.get(
        route + f"/{rule}/versions", headers=headers, params={"cursor": first["next_cursor"]}
    ).json()
    assert len(first["items"]) == 100 and len(second["items"]) == 4
    assert len({row["id"] for row in first["items"] + second["items"]}) == 104
    template = service.store.run(org, run)
    assert template
    owner = service.get(actor, org, workspace, UUID(rule))
    assert owner.project_id
    for _ in range(103):
        service.capture(
            OperationalEvent(
                id=uuid7(),
                type="project.phase.changed",
                occurred_at=datetime.now(UTC),
                organization_id=org,
                workspace_id=workspace,
                project_id=owner.project_id,
                actor_id=context(api, org)[1],
                correlation_id=uuid7(),
                aggregate_type="project",
                aggregate_id=owner.project_id,
                payload=EventContext(phase="active"),
            )
        )
    first = api.client.get(route + f"/{rule}/versions/1/runs", headers=headers).json()
    second = api.client.get(
        route + f"/{rule}/versions/1/runs", headers=headers, params={"cursor": first["next_cursor"]}
    ).json()
    assert len(first["items"]) == 100 and len(second["items"]) == 4
    assert second["next_cursor"] is None
    assert len({row["id"] for row in first["items"] + second["items"]}) == 104
    assert api.client.get(route + f"/{rule}/versions/2/runs", headers=headers).json()["items"] == []


def test_archived_project_evidence_remains_readable_without_writes(api: Api) -> None:
    org, workspace, route, rule, run, _ = active_run(api)
    services = compose(api.session)
    actor, _ = context(api, org)
    owner = services.automation.get(actor, org, workspace, UUID(rule))
    assert owner.project_id
    services.automation.clone(actor, org, workspace, owner.id, 1, 2)
    services.automation.failed(org, run, "fixture_error", False)
    for state in ("closing", "closed", "archived"):
        current = services.projects.require_access(
            actor, org, workspace, owner.project_id, "project.read"
        )
        services.projects.transition(
            actor, org, workspace, owner.project_id, state, current.version, "Archive fixture"
        )
    headers = api.headers("admin")
    for suffix in (
        f"/{rule}",
        f"/{rule}/versions",
        f"/{rule}/versions/1",
        f"/{rule}/versions/2",
        f"/{rule}/versions/1/runs",
        f"/{rule}/runs/{run}",
    ):
        assert api.client.get(route + suffix, headers=headers).status_code == 200
    assert (
        len(
            api.client.get(
                route, headers=headers, params={"project_id": str(owner.project_id)}
            ).json()["items"]
        )
        == 1
    )
    assert (
        api.client.post(route + f"/{rule}/runs/{run}/replay", headers=headers, json={}).status_code
        == 409
    )
    assert (
        api.client.put(
            route + f"/{rule}/versions/2",
            headers=headers,
            json={"expected_revision": 1, "definition": DEFINITION},
        ).status_code
        == 409
    )


def test_replay_manager_cannot_replace_revoked_original_delegation(api: Api) -> None:
    org, workspace, route, rule, run, _ = active_run(api)
    services = compose(api.session)
    services.automation.failed(org, run, "fixture_error", False)
    token = api.invitation(org, workspace)
    replacement = api.accept(org, token)
    result = api.client.post(
        f"/api/v1/organizations/{org}/grants",
        headers=api.headers("admin"),
        json={
            "user_id": str(replacement),
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(org),
        },
    )
    assert result.status_code == 201, result.text
    headers = api.headers("invitee", "invitee@example.com")
    endpoint = route + f"/{rule}/runs/{run}/replay"
    preview = api.client.post(endpoint, headers=headers, json={})
    assert preview.status_code == 200
    _, admin = context(api, org)
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.user_id == admin)
        .values(revoked=True)
    )
    # The requesting replacement retains full management, but the pinned delegator does not.
    assert api.client.get(route + f"/{rule}/runs/{run}", headers=headers).status_code == 200
    result = api.client.post(
        endpoint,
        headers=headers,
        json={
            "dry_run": False,
            "review_sha256": preview.json()["review_sha256"],
            "reason": "Repair",
        },
    )
    assert result.status_code == 403
    unchanged = services.automation.store.run(org, run)
    assert unchanged and unchanged.state == "dead_letter" and unchanged.attempts == 1
