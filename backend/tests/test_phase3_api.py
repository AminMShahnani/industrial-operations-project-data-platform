import base64
from uuid import UUID, uuid7

import pytest
from operations.modules.files.infrastructure.adapters import ClamScanner, S3Storage
from operations.modules.forms.infrastructure.persistence import FormVersionRow
from operations.modules.submissions.infrastructure.persistence import SubmissionRow
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api

pytestmark = pytest.mark.integration


def schema() -> dict[str, object]:
    return {
        "sections": [
            {
                "key": "main",
                "label": "Main",
                "components": [
                    {"key": "quantity", "kind": "integer", "label": "Quantity", "required": True},
                    {
                        "key": "double",
                        "kind": "calculated",
                        "label": "Double",
                        "formula": {
                            "op": "multiply",
                            "args": [
                                {"op": "field", "key": "quantity"},
                                {"op": "literal", "value": 2},
                            ],
                        },
                    },
                    {"key": "acknowledge", "kind": "signature", "label": "Acknowledgement"},
                    {"key": "attachment", "kind": "file", "label": "Attachment"},
                ],
            }
        ]
    }


def setup(api: Api) -> tuple[UUID, UUID, str, str]:
    org = api.organization()
    workspace = api.workspace(org)
    route = f"/api/v1/organizations/{org}/workspaces/{workspace}"
    response = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={"name": "Operational report", "definition": schema()},
    )
    assert response.status_code == 201, response.text
    form = str(response.json()["id"])
    return org, workspace, route, form


def publish(api: Api, route: str, form: str) -> None:
    url = route + f"/forms/{form}/versions/1/publish"
    preview = api.client.post(url, headers=api.headers("admin"), json={"expected_revision": 1})
    assert preview.status_code == 200, preview.text
    applied = api.client.post(
        url,
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "dry_run": False,
            "expected_sha256": preview.json()["content_sha256"],
        },
    )
    assert applied.status_code == 200, applied.text


def draft(api: Api, route: str, form: str, subject: str = "admin") -> str:
    response = api.client.post(
        route + "/submissions", headers=api.headers(subject), json={"form_id": form, "number": 1}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_publication_preview_immutability_concurrency_and_retirement(api: Api) -> None:
    org, workspace, route, form = setup(api)
    url = route + f"/forms/{form}/versions/1"
    token = api.invitation(org, workspace)
    api.accept(org, token)
    assert (
        api.client.get(url, headers=api.headers("invitee", "invitee@example.com")).status_code
        == 403
    )
    assert (
        api.client.post(
            url + "/publish",
            headers=api.headers("admin"),
            json={"expected_revision": 1, "dry_run": False},
        ).status_code
        == 409
    )
    publish(api, route, form)
    assert (
        api.client.get(url, headers=api.headers("invitee", "invitee@example.com")).status_code
        == 200
    )
    assert (
        api.client.put(
            url, headers=api.headers("admin"), json={"definition": schema(), "expected_revision": 2}
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            route + "/submissions",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"form_id": form, "number": 1},
        ).status_code
        == 403
    )
    cloned = api.client.post(
        route + f"/forms/{form}/versions",
        headers=api.headers("admin"),
        json={"source_number": 1, "number": 2},
    )
    assert cloned.status_code == 201 and cloned.json()["state"] == "draft"
    wrong = api.client.put(
        route + f"/forms/{form}/versions/2",
        headers=api.headers("admin"),
        json={"definition": schema(), "expected_revision": 2},
    )
    assert wrong.status_code == 409
    old_draft = draft(api, route, form)
    retired = api.client.post(
        url + "/lifecycle",
        headers=api.headers("admin"),
        json={
            "state": "retired",
            "expected_revision": 2,
            "dry_run": False,
            "reason": "Retired definition",
        },
    )
    assert retired.status_code == 200, retired.text
    assert (
        api.client.post(
            route + "/submissions",
            headers=api.headers("admin"),
            json={"form_id": form, "number": 1},
        ).status_code
        == 409
    )
    assert (
        api.client.put(
            route + f"/submissions/{old_draft}",
            headers=api.headers("admin"),
            json={"values": {"fields": {"quantity": 1}}, "expected_revision": 1},
        ).status_code
        == 409
    )


def test_exact_version_validation_submission_snapshot_and_idempotency(api: Api) -> None:
    _, _, route, form = setup(api)
    publish(api, route, form)
    identifier = draft(api, route, form)
    url = route + f"/submissions/{identifier}"
    check = api.client.post(
        url + "/validate", headers=api.headers("admin"), json={"values": {"fields": {}}}
    )
    assert check.status_code == 200 and any(
        issue["code"] == "required" for issue in check.json()["issues"]
    )
    for fields in (
        {"quantity": True},
        {"quantity": 2, "double": "99"},
        {"quantity": 1, "unknown": 3},
    ):
        assert (
            api.client.put(
                url,
                headers=api.headers("admin"),
                json={"expected_revision": 1, "values": {"fields": fields}},
            ).status_code
            == 422
        )
    saved = api.client.put(
        url,
        headers=api.headers("admin"),
        json={
            "expected_revision": 1,
            "values": {"fields": {"quantity": 7, "acknowledge": "I acknowledge this record"}},
        },
    )
    assert saved.status_code == 200 and saved.json()["values"]["fields"]["double"] == "14", (
        saved.text
    )
    command = {
        "expected_revision": 2,
        "idempotency_key": str(uuid7()),
        "reason": "Reviewed my report",
    }
    response = api.client.post(url + "/submit", headers=api.headers("admin"), json=command)
    assert response.status_code == 200, response.text
    assert (
        response.json()["state"] == "submitted"
        and response.json()["signatures"][0]["reason"] == command["reason"]
    )
    assert (
        api.client.post(url + "/submit", headers=api.headers("admin"), json=command).json()
        == response.json()
    )
    assert (
        api.client.put(
            url,
            headers=api.headers("admin"),
            json={"expected_revision": 3, "values": {"fields": {"quantity": 9}}},
        ).status_code
        == 409
    )
    row = api.session.scalar(select(SubmissionRow).where(SubmissionRow.id == UUID(identifier)))
    assert row and row.form_number == 1 and row.submit_key == UUID(str(command["idempotency_key"]))
    with pytest.raises(DBAPIError), api.session.begin_nested():
        api.session.execute(
            text("UPDATE submissions SET values='{}' WHERE id=:id"), {"id": identifier}
        )
    with pytest.raises(DBAPIError), api.session.begin_nested():
        api.session.execute(text("DELETE FROM submissions WHERE id=:id"), {"id": identifier})


def test_pinned_library_snapshot_and_cross_tenant_isolation(api: Api) -> None:
    _, _, route, form = setup(api)
    library = api.client.post(
        route + "/form-library",
        headers=api.headers("admin"),
        json={
            "code": "reusable",
            "version": 1,
            "kind": "field",
            "definition": {
                "sections": [
                    {
                        "key": "library",
                        "label": "Library",
                        "components": [{"key": "notes", "kind": "textarea", "label": "Notes"}],
                    }
                ]
            },
        },
    )
    assert library.status_code == 201, library.text
    definition = {
        "sections": [
            {
                "key": "main",
                "label": "Main",
                "references": [{"artifact_id": library.json()["id"], "version": 1}],
            }
        ]
    }
    url = route + f"/forms/{form}/versions/1"
    assert (
        api.client.put(
            url,
            headers=api.headers("admin"),
            json={"expected_revision": 1, "definition": definition},
        ).status_code
        == 200
    )
    preview = api.client.post(
        url + "/publish", headers=api.headers("admin"), json={"expected_revision": 2}
    )
    assert (
        preview.status_code == 200
        and preview.json()["definition"]["sections"][0]["components"][0]["key"] == "notes"
    )
    assert preview.json()["definition"]["sections"][0]["references"] == []
    other = api.organization("other")
    other_ws = api.workspace(other, "other")
    other_route = f"/api/v1/organizations/{other}/workspaces/{other_ws}"
    response = api.client.post(
        other_route + "/forms",
        headers=api.headers("other"),
        json={"name": "Other", "definition": definition},
    )
    assert response.status_code == 201
    assert (
        api.client.post(
            other_route + f"/forms/{response.json()['id']}/versions/1/publish",
            headers=api.headers("other"),
            json={"expected_revision": 1},
        ).status_code
        == 422
    )
    assert (
        api.client.get(
            other_route + f"/forms/{form}/versions/1", headers=api.headers("other")
        ).status_code
        == 404
    )
    assert api.client.get(url, headers=api.headers()).status_code in {403, 404}


def test_attachment_scanner_content_and_owner_boundaries(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, workspace, route, form = setup(api)
    publish(api, route, form)
    identifier = draft(api, route, form)
    url = route + f"/submissions/{identifier}"
    body = {
        "name": "evidence.txt",
        "content_type": "text/plain",
        "content_base64": base64.b64encode(b"Evidence").decode(),
    }
    assert (
        api.client.post(url + "/files", headers=api.headers("admin"), json=body).status_code == 503
    )
    monkeypatch.setattr(ClamScanner, "clean", lambda self, data: False)
    assert (
        api.client.post(url + "/files", headers=api.headers("admin"), json=body).status_code == 422
    )
    monkeypatch.setattr(ClamScanner, "clean", lambda self, data: True)
    stored: list[bytes] = []
    monkeypatch.setattr(S3Storage, "put", lambda self, key, data, content_type: stored.append(data))
    monkeypatch.setattr(
        S3Storage,
        "signed_download",
        lambda self, key, name, content_type: "https://private.example.test/signed",
    )
    assert (
        api.client.post(
            url + "/files", headers=api.headers("admin"), json={**body, "content_type": "image/png"}
        ).status_code
        == 422
    )
    assert (
        api.client.post(
            url + "/files", headers=api.headers("admin"), json={**body, "name": "../evil.txt"}
        ).status_code
        == 422
    )
    uploaded = api.client.post(url + "/files", headers=api.headers("admin"), json=body)
    assert uploaded.status_code == 201 and stored == [b"Evidence"], uploaded.text
    file_id = uploaded.json()["id"]
    assert (
        api.client.post(route + f"/files/{file_id}/download", headers=api.headers("admin")).json()[
            "expires_in"
        ]
        == 60
    )
    token = api.invitation(org, workspace, "Contributor")
    api.accept(org, token)
    assert (
        api.client.post(
            route + f"/files/{file_id}/download",
            headers=api.headers("invitee", "invitee@example.com"),
        ).status_code
        == 403
    )
    other_draft = draft(api, route, form, "invitee")
    assert (
        api.client.put(
            route + f"/submissions/{other_draft}",
            headers=api.headers("invitee", "invitee@example.com"),
            json={
                "expected_revision": 1,
                "values": {"fields": {"quantity": 1, "attachment": file_id}},
            },
        ).status_code
        == 422
    )


def test_published_definition_database_mutation_and_history_guard(api: Api) -> None:
    _, _, route, form = setup(api)
    publish(api, route, form)
    row = api.session.scalar(select(FormVersionRow).where(FormVersionRow.form_id == UUID(form)))
    assert row
    for statement in (
        "UPDATE form_versions SET definition='{}', revision=revision+1 WHERE id=:id",
        "UPDATE form_versions SET state='draft', revision=revision+1 WHERE id=:id",
        "DELETE FROM form_versions WHERE id=:id",
        "TRUNCATE forms CASCADE",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(statement), {"id": row.id})


def test_component_privacy_lookup_eligibility_and_contributor_non_escalation(api: Api) -> None:
    org, workspace, route, _ = setup(api)
    token = api.invitation(org, workspace, "Contributor")
    api.accept(org, token)
    other_ws = api.workspace(org)
    other_token = api.invitation(org, other_ws, "Viewer", email="elsewhere@example.com")
    api.accept(org, other_token, "elsewhere", "elsewhere@example.com")
    definition = {
        "sections": [
            {
                "key": "main",
                "label": "Main",
                "components": [
                    {"key": "note", "kind": "text", "label": "Note", "required": True},
                    {
                        "key": "private_note",
                        "kind": "text",
                        "label": "Private",
                        "permissions": {"read": "owner", "write": "owner"},
                    },
                    {
                        "key": "secret",
                        "kind": "text",
                        "label": "Secret",
                        "permissions": {"read": "manager", "write": "manager"},
                        "default": {"op": "literal", "value": "manager-only"},
                    },
                    {"key": "assignee", "kind": "user", "label": "User"},
                ],
            }
        ]
    }
    response = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={"name": "Private form", "definition": definition},
    )
    assert response.status_code == 201
    form = str(response.json()["id"])
    publish(api, route, form)
    headers = api.headers("invitee", "invitee@example.com")
    version = route + f"/forms/{form}/versions/1"
    public = api.client.get(version, headers=headers)
    assert "manager-only" not in public.text and "Secret" not in public.text
    eligible = api.client.get(
        version + "/lookups/assignee?email=ADMIN@example.com", headers=headers
    )
    assert eligible.status_code == 200 and len(eligible.json()["items"]) == 1
    assert (
        api.client.get(
            version + "/lookups/assignee?email=elsewhere@example.com", headers=headers
        ).json()["items"]
        == []
    )
    identifier = draft(api, route, form, "invitee")
    url = route + f"/submissions/{identifier}"
    assert api.client.get(url, headers=api.headers("admin")).status_code == 403
    assert (
        api.client.put(
            url,
            headers=headers,
            json={
                "expected_revision": 1,
                "values": {"fields": {"note": "Report", "secret": "injected"}},
            },
        ).status_code
        == 422
    )
    saved = api.client.put(
        url,
        headers=headers,
        json={
            "expected_revision": 1,
            "values": {"fields": {"note": "Report", "private_note": "Owner only"}},
        },
    )
    assert saved.status_code == 200, saved.text
    submitted = api.client.post(
        url + "/submit",
        headers=headers,
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Finished"},
    )
    assert submitted.status_code == 200, submitted.text
    manager = api.client.get(url, headers=api.headers("admin"))
    assert manager.status_code == 200 and "Owner only" not in manager.text
    assert api.client.get(url, headers=api.headers()).status_code in {403, 404}
    assert (
        api.client.post(
            version + "/publish", headers=headers, json={"expected_revision": 2}
        ).status_code
        == 403
    )


def test_publication_cycle_invalid_library_and_populated_rollback(api: Api) -> None:
    _, _, route, form = setup(api)
    definition = {
        "sections": [
            {
                "key": "main",
                "label": "Main",
                "components": [
                    {
                        "key": "cycle",
                        "kind": "calculated",
                        "label": "Cycle",
                        "formula": {"op": "field", "key": "cycle"},
                    }
                ],
            }
        ]
    }
    url = route + f"/forms/{form}/versions/1"
    assert (
        api.client.put(
            url,
            headers=api.headers("admin"),
            json={"definition": definition, "expected_revision": 1},
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            url + "/publish", headers=api.headers("admin"), json={"expected_revision": 2}
        ).status_code
        == 422
    )
    invalid_library = api.client.post(
        route + "/form-library",
        headers=api.headers("admin"),
        json={"code": "cycle", "version": 1, "kind": "field", "definition": definition},
    )
    assert invalid_library.status_code == 422
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("464245e2e729")
    assert revision
    with (
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
        pytest.raises(RuntimeError, match="populated Phase 3"),
    ):
        revision.module.downgrade()


def test_trusted_defaults_port_and_nested_signature_evidence(api: Api) -> None:
    from operations.composition import compose
    from operations.modules.forms.application.contracts import (
        Form,
        FormDefinition,
        FormValues,
        FormVersion,
    )
    from operations.modules.identity.application.contracts import Principal, RequestContext

    org, workspace, route, _ = setup(api)
    services = compose(api.session, Principal("https://identity.example.test", "admin"))

    class Context:
        def shift(
            self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, user_id: UUID
        ) -> str | None:
            return "morning"

        def previous_approved(
            self,
            organization_id: UUID,
            workspace_id: UUID,
            form_id: UUID,
            owner_id: UUID,
            field_key: str,
        ) -> int:
            assert field_key == "count"
            return 7

    services.forms.default_context = Context()
    definition = FormDefinition.model_validate(
        {
            "sections": [
                {
                    "key": "main",
                    "label": "Main",
                    "components": [
                        {
                            "key": "shift",
                            "kind": "select",
                            "label": "Shift",
                            "choices": ["morning"],
                            "default": {"op": "context", "key": "shift"},
                        },
                        {
                            "key": "previous",
                            "kind": "integer",
                            "label": "Previous",
                            "source": {"previous_approved_key": "count"},
                        },
                    ],
                }
            ]
        }
    )
    form = Form(id=uuid7(), organization_id=org, workspace_id=workspace, name="Defaults")
    version = FormVersion(
        id=uuid7(),
        organization_id=org,
        workspace_id=workspace,
        form_id=form.id,
        number=1,
        state="published",
        definition=definition,
    )
    context = RequestContext(Principal("https://identity.example.test", "admin"), uuid7(), uuid7())
    result = services.forms.evaluate(context, form, version, FormValues(), True)
    assert result.issues == [] and result.values.fields == {"shift": "morning", "previous": 7}
    services.forms.default_context = None
    missing = services.forms.evaluate(context, form, version, FormValues(), True)
    assert {issue.code for issue in missing.issues} >= {
        "default_context_unavailable",
        "approved_default_unavailable",
    }
    repeat = {
        "sections": [
            {
                "key": "main",
                "label": "Main",
                "components": [
                    {
                        "key": "items",
                        "kind": "table",
                        "label": "Items",
                        "children": [
                            {"key": "ack", "kind": "signature", "label": "Acknowledgement"}
                        ],
                    }
                ],
            }
        ]
    }
    created = api.client.post(
        route + "/forms",
        headers=api.headers("admin"),
        json={"name": "Acknowledgements", "definition": repeat},
    )
    assert created.status_code == 201
    identifier = str(created.json()["id"])
    publish(api, route, identifier)
    submission = draft(api, route, identifier)
    url = route + f"/submissions/{submission}"
    saved = api.client.put(
        url,
        headers=api.headers("admin"),
        json={"expected_revision": 1, "values": {"fields": {"items": [{"ack": "I acknowledge"}]}}},
    )
    assert saved.status_code == 200, saved.text
    response = api.client.post(
        url + "/submit",
        headers=api.headers("admin"),
        json={
            "expected_revision": 2,
            "idempotency_key": str(uuid7()),
            "reason": "Acknowledged row",
        },
    )
    assert (
        response.status_code == 200 and response.json()["signatures"][0]["key"] == "items[0].ack"
    ), response.text


def test_failed_file_metadata_write_compensates_only_new_object(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    from operations.contracts import ServiceError
    from operations.modules.files.infrastructure.persistence import FileRepository

    _, _, route, form = setup(api)
    publish(api, route, form)
    identifier = draft(api, route, form)
    objects: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(ClamScanner, "clean", lambda self, data: True)
    monkeypatch.setattr(S3Storage, "put", lambda self, key, data, content_type: objects.append(key))
    monkeypatch.setattr(S3Storage, "delete", lambda self, key: deleted.append(key))

    def fail(*args: object) -> None:
        raise ServiceError(503, "metadata_unavailable")

    monkeypatch.setattr(FileRepository, "add", fail)
    response = api.client.post(
        route + f"/submissions/{identifier}/files",
        headers=api.headers("admin"),
        json={
            "name": "evidence.txt",
            "content_type": "text/plain",
            "content_base64": base64.b64encode(b"Evidence").decode(),
        },
    )
    assert response.status_code == 503
    assert len(objects) == 1 and deleted == objects
    assert f"/submissions/{identifier}/" in objects[0]
