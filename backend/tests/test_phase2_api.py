import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from openpyxl import Workbook
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.master_data.application.contracts import (
    DataRecord,
    DataSchema,
    DataScope,
    DataType,
    RegistryKind,
)
from operations.modules.master_data.infrastructure.persistence import DataRecordRow
from operations.modules.projects.infrastructure.persistence import ProjectMembershipRow
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api

pytestmark = pytest.mark.integration


def project(api: Api, organization: UUID, workspace: UUID) -> str:
    response = api.client.post(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects",
        headers=api.headers("admin"),
        json={"name": "Neutral project"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def type_definition(api: Api, organization: UUID, workspace: UUID, code: str = "locations") -> str:
    response = api.client.post(
        f"/api/v1/organizations/{organization}/master-data/types",
        headers=api.headers("admin"),
        json={
            "scope": "workspace",
            "workspace_id": str(workspace),
            "code": code,
            "name": "Locations",
            "registry": "location",
            "definition": {
                "fields": [
                    {"key": "latitude", "kind": "decimal", "required": True},
                    {"key": "enabled", "kind": "boolean"},
                ]
            },
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_project_context_lifecycle_preview_concurrency_and_history(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    identifier = project(api, organization, workspace)
    route = f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects/{identifier}"
    assert api.client.get(route, headers=api.headers()).status_code == 403
    assert (
        api.client.put(
            route,
            headers=api.headers("admin"),
            json={
                "name": "Bad dates",
                "expected_version": 1,
                "context": {"starts_on": "2026-10-10", "ends_on": "2026-10-01"},
            },
        ).status_code
        == 422
    )
    assert (
        api.client.put(
            route,
            headers=api.headers("admin"),
            json={
                "name": "Bad reference",
                "expected_version": 1,
                "context": {"location_ids": [str(uuid7())]},
            },
        ).status_code
        == 422
    )
    preview = api.client.post(
        route + "/transitions",
        headers=api.headers("admin"),
        json={"state": "active", "expected_version": 1, "reason": "Ready"},
    )
    assert preview.status_code == 200 and preview.json()["version"] == 2
    assert api.client.get(route, headers=api.headers("admin")).json()["state"] == "planned"
    assert (
        api.client.post(
            route + "/transitions",
            headers=api.headers("admin"),
            json={"state": "closed", "expected_version": 1, "reason": "Invalid", "dry_run": False},
        ).status_code
        == 422
    )
    for version, state in enumerate(
        ("active", "suspended", "active", "closing", "closed", "archived"), start=1
    ):
        response = api.client.post(
            route + "/transitions",
            headers=api.headers("admin"),
            json={
                "state": state,
                "expected_version": version,
                "reason": "Controlled transition",
                "dry_run": False,
            },
        )
        assert response.status_code == 200, response.text
    assert (
        api.client.put(
            route,
            headers=api.headers("admin"),
            json={"name": "After archive", "context": {}, "expected_version": 7},
        ).status_code
        == 409
    )
    events = api.session.scalars(
        select(AuditRow).where(AuditRow.aggregate_id == UUID(identifier))
    ).all()
    assert sum(event.type == "project.transitioned" for event in events) == 6


def test_department_membership_requires_grant_and_direct_access_is_independent(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    user = api.accept(organization, api.invitation(organization, workspace))
    identifier = project(api, organization, workspace)
    root = f"/api/v1/organizations/{organization}/workspaces/{workspace}"
    group = api.client.post(
        root + "/groups",
        headers=api.headers("admin"),
        json={"kind": "department", "name": "Operations"},
    )
    assert group.status_code == 201
    group_id = group.json()["id"]
    member = api.client.post(
        f"{root}/groups/{group_id}/memberships",
        headers=api.headers("admin"),
        json={"user_id": str(user)},
    )
    assert member.status_code == 201
    route = f"{root}/projects/{identifier}"
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 403
    grant = api.client.post(
        route + "/department-grants",
        headers=api.headers("admin"),
        json={"department_id": group_id, "role": "Viewer"},
    )
    assert grant.status_code == 201
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 200
    assert (
        api.client.put(
            route,
            headers=api.headers("invitee"),
            json={"name": "Escalate", "context": {}, "expected_version": 1},
        ).status_code
        == 403
    )
    direct = api.client.post(
        route + "/memberships",
        headers=api.headers("admin"),
        json={"user_id": str(user), "role": "Contributor"},
    )
    assert direct.status_code == 201
    assert (
        api.client.post(
            f"{root}/groups/{group_id}/memberships/{member.json()['id']}/revoke",
            headers=api.headers("admin"),
        ).status_code
        == 204
    )
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 200
    assert (
        api.client.post(
            f"{route}/memberships/{direct.json()['id']}/revoke", headers=api.headers("admin")
        ).status_code
        == 204
    )
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 403
    assert api.session.get(ProjectMembershipRow, UUID(direct.json()["id"])) is not None


def test_project_grants_expire_and_cannot_cross_workspace_or_tenant(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    other_workspace = api.workspace(organization)
    other_organization = api.organization("other")
    user = api.accept(organization, api.invitation(organization, workspace))
    identifier = project(api, organization, workspace)
    route = f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects/{identifier}"
    expired = api.client.post(
        route + "/memberships",
        headers=api.headers("admin"),
        json={
            "user_id": str(user),
            "role": "Viewer",
            "valid_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        },
    )
    assert expired.status_code == 201
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 403
    assert (
        api.client.post(
            route + "/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(user), "role": "Viewer", "valid_from": "2026-01-01T00:00:00"},
        ).status_code
        == 422
    )
    for tenant, target_workspace in (
        (organization, other_workspace),
        (other_organization, workspace),
    ):
        response = api.client.get(
            f"/api/v1/organizations/{tenant}/workspaces/{target_workspace}/projects/{identifier}",
            headers=api.headers("admin"),
        )
        assert response.status_code in {403, 404}
    with pytest.raises(IntegrityError), api.session.begin_nested():
        api.session.add(
            ProjectMembershipRow(
                id=uuid7(),
                organization_id=organization,
                workspace_id=other_workspace,
                project_id=UUID(identifier),
                user_id=user,
                role="Viewer",
                revoked=False,
            )
        )
        api.session.flush()


def test_typed_master_data_reference_status_and_optimistic_update(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    type_id = type_definition(api, organization, workspace)
    root = f"/api/v1/organizations/{organization}/master-data/types/{type_id}"
    body = {
        "code": "SITE-1",
        "name": "Site",
        "values": {"fields": {"latitude": "12.123456", "enabled": True}},
    }
    record = api.client.post(root + "/records", headers=api.headers("admin"), json=body)
    assert record.status_code == 201, record.text
    assert (
        api.client.post(root + "/records", headers=api.headers("admin"), json=body).status_code
        == 409
    )
    for invalid in (12.1, "NaN", "1.1234567", True):
        invalid_body = {**body, "code": "BAD", "values": {"fields": {"latitude": invalid}}}
        assert (
            api.client.post(
                root + "/records", headers=api.headers("admin"), json=invalid_body
            ).status_code
            == 422
        )
    create = api.client.post(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects",
        headers=api.headers("admin"),
        json={"name": "Located", "context": {"location_ids": [record.json()["id"]]}},
    )
    assert create.status_code == 201
    changed = {
        "name": "Old site",
        "status": "deprecated",
        "values": body["values"],
        "expected_version": 1,
    }
    assert (
        api.client.put(
            f"{root}/records/{record.json()['id']}", headers=api.headers("admin"), json=changed
        ).status_code
        == 200
    )
    assert (
        api.client.put(
            f"{root}/records/{record.json()['id']}", headers=api.headers("admin"), json=changed
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects",
            headers=api.headers("admin"),
            json={"name": "Bad location", "context": {"location_ids": [record.json()["id"]]}},
        ).status_code
        == 422
    )
    assert api.session.get(DataRecordRow, UUID(record.json()["id"])) is not None


def test_csv_import_preview_duplicate_detection_atomic_apply_and_export(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    type_id = type_definition(api, organization, workspace)
    route = f"/api/v1/organizations/{organization}/master-data/types/{type_id}"
    bad = (
        b"code,name,latitude,enabled\nA,Site,1.0,true\nA,Duplicate,2.0,false\nB,Invalid,NaN,false\n"
    )
    request = {
        "content_base64": base64.b64encode(bad).decode(),
        "format": "csv",
        "expected_type_version": 1,
    }
    preview = api.client.post(route + "/imports", headers=api.headers("admin"), json=request)
    assert preview.status_code == 200 and len(preview.json()["issues"]) == 2
    assert api.client.get(route + "/records", headers=api.headers("admin")).json()["items"] == []
    request.update({"dry_run": False, "expected_sha256": preview.json()["source_sha256"]})
    assert (
        api.client.post(route + "/imports", headers=api.headers("admin"), json=request).status_code
        == 422
    )
    good = b"code,name,latitude,enabled\nA,Site,1.0,true\nB,Second,2.0,false\n"
    request = {
        "content_base64": base64.b64encode(good).decode(),
        "format": "csv",
        "expected_type_version": 1,
    }
    preview = api.client.post(route + "/imports", headers=api.headers("admin"), json=request).json()
    request["dry_run"] = False
    assert (
        api.client.post(route + "/imports", headers=api.headers("admin"), json=request).status_code
        == 409
    )
    request["expected_sha256"] = preview["source_sha256"]
    applied = api.client.post(route + "/imports", headers=api.headers("admin"), json=request)
    assert applied.status_code == 200 and len(applied.json()["rows"]) == 2
    assert (
        api.client.post(route + "/imports", headers=api.headers("admin"), json=request).status_code
        == 422
    )
    exported = api.client.get(route + "/export", headers=api.headers("admin"))
    assert exported.status_code == 200 and applied.json()["rows"][0]["id"] in exported.text
    assert "code,name,status" in exported.text


def test_xlsx_import_rejects_formulas_and_accepts_typed_values(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    type_id = type_definition(api, organization, workspace)
    route = f"/api/v1/organizations/{organization}/master-data/types/{type_id}/imports"
    for value, status in (("=1+1", 422), ("12.5", 200)):
        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.append(["code", "name", "latitude", "enabled"])
        sheet.append(["XLSX-1", "Excel site", value, True])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        response = api.client.post(
            route,
            headers=api.headers("admin"),
            json={
                "format": "xlsx",
                "content_base64": base64.b64encode(output.getvalue()).decode(),
                "expected_type_version": 1,
            },
        )
        assert response.status_code == status, response.text
        if status == 200:
            assert not response.json()["issues"]


def test_global_reference_is_operator_published_and_tenant_read_only(api: Api) -> None:
    organization = api.organization()
    platform = Principal("https://identity.example.test", "platform")
    services = compose(api.session, platform)
    definition = DataType(
        id=uuid7(),
        organization_id=None,
        workspace_id=None,
        project_id=None,
        scope=DataScope.GLOBAL,
        code="units",
        name="Units",
        registry=RegistryKind.UNIT,
        definition=DataSchema(),
    )
    record = DataRecord(
        id=uuid7(), organization_id=None, type_id=definition.id, code="m", name="metre"
    )
    with api.session.begin_nested():
        services.master_data.publish_global(
            RequestContext(platform, uuid7(), uuid7()),
            definition,
            [record],
            "Operator approved reference fixture",
        )
    route = f"/api/v1/organizations/{organization}/master-data/types/{definition.id}"
    assert api.client.get(route + "/records", headers=api.headers("admin")).status_code == 200
    assert (
        api.client.post(
            route + "/records", headers=api.headers("admin"), json={"code": "ft", "name": "foot"}
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/master-data/types",
            headers=api.headers("admin"),
            json={"scope": "global", "code": "bad", "name": "Unauthorized", "definition": {}},
        ).status_code
        == 403
    )
    with pytest.raises(IntegrityError), api.session.begin_nested():
        api.session.add(
            DataRecordRow(
                id=uuid7(),
                organization_id=organization,
                owner_id=organization,
                type_id=definition.id,
                code="BAD",
                name="Wrong owner",
                status="active",
                values={"fields": {}},
                version=1,
            )
        )
        api.session.flush()


def test_phase2_populated_downgrade_refuses_before_drop(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    identifier = project(api, organization, workspace)
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("99e791752349")
    assert revision is not None
    with (
        Operations.context(MigrationContext.configure(api.session.connection())),
        pytest.raises(RuntimeError, match="Refusing populated"),
    ):
        revision.module.downgrade()
    assert (
        api.client.get(
            f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects/{identifier}",
            headers=api.headers("admin"),
        ).status_code
        == 200
    )


def test_user_reactivation_does_not_restore_project_or_department_access(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    user = api.accept(organization, api.invitation(organization, workspace))
    identifier = project(api, organization, workspace)
    root = f"/api/v1/organizations/{organization}/workspaces/{workspace}"
    route = f"{root}/projects/{identifier}"
    direct = api.client.post(
        route + "/memberships",
        headers=api.headers("admin"),
        json={"user_id": str(user), "role": "ProjectManager"},
    )
    assert direct.status_code == 201
    group = api.client.post(
        root + "/groups",
        headers=api.headers("admin"),
        json={"kind": "department", "name": "Department"},
    ).json()
    group_id = group["id"]
    assert (
        api.client.post(
            f"{root}/groups/{group_id}/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(user), "manager": True},
        ).status_code
        == 201
    )
    assert (
        api.client.post(
            route + "/department-grants",
            headers=api.headers("admin"),
            json={"department_id": group_id, "role": "Viewer"},
        ).status_code
        == 201
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/users/{user}/revoke",
            headers=api.headers("admin"),
        ).status_code
        == 204
    )
    assert api.accept(organization, api.invitation(organization, workspace)) == user
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 403
    member = api.session.get(ProjectMembershipRow, UUID(direct.json()["id"]))
    assert member is not None
    api.session.refresh(member)
    assert member is not None and member.revoked


def test_database_definition_history_and_department_only_invariants(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    identifier = project(api, organization, workspace)
    type_id = type_definition(api, organization, workspace)
    root = f"/api/v1/organizations/{organization}/master-data/types/{type_id}"
    record = api.client.post(
        root + "/records",
        headers=api.headers("admin"),
        json={
            "code": "SITE",
            "name": "Site",
            "values": {"fields": {"latitude": "1.0"}},
        },
    )
    assert record.status_code == 201
    for statement in (
        "UPDATE projects SET lifecycle = '{}'::jsonb",
        "UPDATE master_data_types SET definition = '{}'::jsonb",
        "UPDATE master_data_records SET code = 'tampered'",
        "UPDATE project_memberships SET role = 'Viewer'",
        "DELETE FROM master_data_records",
        "TRUNCATE master_data_records",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(statement))
    group_root = f"/api/v1/organizations/{organization}/workspaces/{workspace}"
    team = api.client.post(
        group_root + "/groups", headers=api.headers("admin"), json={"kind": "team", "name": "Team"}
    ).json()
    assert (
        api.client.post(
            f"{group_root}/projects/{identifier}/department-grants",
            headers=api.headers("admin"),
            json={"department_id": team["id"], "role": "Viewer"},
        ).status_code
        == 404
    )
    from operations.modules.projects.infrastructure.persistence import DepartmentProjectGrantRow

    with pytest.raises(IntegrityError), api.session.begin_nested():
        api.session.add(
            DepartmentProjectGrantRow(
                id=uuid7(),
                organization_id=organization,
                workspace_id=workspace,
                project_id=UUID(identifier),
                department_id=UUID(team["id"]),
                role="Viewer",
                revoked=False,
            )
        )
        api.session.flush()


def test_direct_project_context_discovery_does_not_grant_workspace_administration(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    other_workspace = api.workspace(organization)
    identifier = project(api, organization, workspace)
    other_project = project(api, organization, workspace)
    root = f"/api/v1/organizations/{organization}"
    token = api.client.post(
        root + "/invitations",
        headers=api.headers("admin"),
        json={
            "email": "project-only@example.com",
            "role": "Viewer",
            "scope_type": "organization",
            "scope_id": str(organization),
        },
    ).json()["token"]
    user = api.accept(organization, token, "project-only", "project-only@example.com")
    route = f"{root}/workspaces/{workspace}/projects/{identifier}"
    assert (
        api.client.post(
            route + "/memberships",
            headers=api.headers("admin"),
            json={"user_id": str(user), "role": "Viewer"},
        ).status_code
        == 201
    )
    headers = api.headers("project-only", "project-only@example.com")
    listed = api.client.get(root + "/workspaces", headers=headers).json()
    assert [item["id"] for item in listed["items"]] == [str(workspace)]
    assert api.client.get(f"{root}/workspaces/{workspace}", headers=headers).status_code == 200
    assert (
        api.client.get(f"{root}/workspaces/{other_workspace}", headers=headers).status_code == 403
    )
    assert api.client.get(route, headers=headers).status_code == 200
    assert (
        api.client.get(
            f"{root}/workspaces/{workspace}/projects/{other_project}", headers=headers
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"{root}/workspaces/{workspace}/projects", headers=headers, json={"name": "Escalate"}
        ).status_code
        == 403
    )
    assert (
        api.client.put(
            f"{root}/workspaces/{workspace}",
            headers=headers,
            json={"name": "Escalate", "expected_version": 1},
        ).status_code
        == 403
    )


def test_master_data_cursor_export_and_import_recheck_scope(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    type_id = type_definition(api, organization, workspace)
    route = f"/api/v1/organizations/{organization}/master-data/types/{type_id}"
    data = (
        "code,name,latitude\n" + "\n".join(f"SITE-{index},Site {index},1.0" for index in range(101))
    ).encode()
    body = {
        "content_base64": base64.b64encode(data).decode(),
        "format": "csv",
        "expected_type_version": 1,
    }
    preview = api.client.post(route + "/imports", headers=api.headers("admin"), json=body).json()
    body.update({"dry_run": False, "expected_sha256": preview["source_sha256"]})
    assert (
        api.client.post(route + "/imports", headers=api.headers("admin"), json=body).status_code
        == 200
    )
    first = api.client.get(route + "/records", headers=api.headers("admin")).json()
    assert len(first["items"]) == 100 and first["next_cursor"]
    last = api.client.get(
        route + "/records", headers=api.headers("admin"), params={"cursor": first["next_cursor"]}
    ).json()
    assert len(last["items"]) == 1 and last["next_cursor"] is None
    exported = api.client.get(
        route + "/export", headers={**api.headers("admin"), "Origin": "http://localhost:5173"}
    )
    assert exported.headers["X-Next-Cursor"] == first["next_cursor"]
    assert "X-Next-Cursor" in exported.headers["Access-Control-Expose-Headers"]
    assert api.client.get(route + "/records", headers=api.headers()).status_code == 403
    api.accept(organization, api.invitation(organization, workspace))
    assert (
        api.client.post(route + "/imports", headers=api.headers("invitee"), json=body).status_code
        == 403
    )


@pytest.mark.parametrize(
    "kind,options,good,bad",
    [
        ("integer", {}, 12, "12"),
        ("boolean", {}, False, "false"),
        ("date", {}, "2026-10-05", "2026-02-30"),
        ("enum", {"choices": ["ready", "paused"]}, "ready", "unknown"),
        ("text", {}, "Plain text", 12),
    ],
)
def test_master_data_field_kinds_are_explicit(
    api: Api, kind: str, options: dict[str, object], good: object, bad: object
) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    result = api.client.post(
        f"/api/v1/organizations/{organization}/master-data/types",
        headers=api.headers("admin"),
        json={
            "scope": "workspace",
            "workspace_id": str(workspace),
            "code": "typed",
            "name": "Typed records",
            "definition": {"fields": [{"key": "value", "kind": kind, "required": True, **options}]},
        },
    )
    assert result.status_code == 201
    route = f"/api/v1/organizations/{organization}/master-data/types/{result.json()['id']}/records"
    assert (
        api.client.post(
            route,
            headers=api.headers("admin"),
            json={"code": "VALID", "name": "Valid", "values": {"fields": {"value": good}}},
        ).status_code
        == 201
    )
    assert (
        api.client.post(
            route,
            headers=api.headers("admin"),
            json={"code": "INVALID", "name": "Invalid", "values": {"fields": {"value": bad}}},
        ).status_code
        == 422
    )
