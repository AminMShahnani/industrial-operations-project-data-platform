import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from operations.composition import compose
from operations.main import create_app
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal
from operations.modules.identity.infrastructure.oidc import OidcVerifier
from operations.modules.identity.infrastructure.persistence import InvitationRow, UserRow
from operations.modules.organizations.infrastructure.persistence import OrganizationRow
from operations.platform.config import Settings
from operations.platform.database import create_database_engine
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from test_oidc import Resolver, access_token, configured
from test_oidc import signing_key as signing_key

pytestmark = pytest.mark.integration


@dataclass
class Api:
    client: TestClient
    session: Session
    key: rsa.RSAPrivateKey
    settings: Settings

    def headers(
        self, subject: str = "platform", email: str = "platform@example.com"
    ) -> dict[str, str]:
        return {"Authorization": "Bearer " + access_token(self.key, subject, email)}

    def organization(self, subject: str = "admin") -> UUID:
        response = self.client.post(
            "/api/v1/organizations",
            headers=self.headers(),
            json={
                "name": "Tenant",
                "admin_subject": subject,
                "admin_email": f"{subject}@example.com",
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["id"])

    def workspace(self, organization: UUID, subject: str = "admin") -> UUID:
        response = self.client.post(
            f"/api/v1/organizations/{organization}/workspaces",
            headers=self.headers(subject),
            json={"name": "Workspace"},
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["id"])

    def invitation(
        self,
        organization: UUID,
        workspace: UUID,
        role: str = "Viewer",
        subject: str = "admin",
        email: str = "invitee@example.com",
    ) -> str:
        response = self.client.post(
            f"/api/v1/organizations/{organization}/invitations",
            headers=self.headers(subject),
            json={
                "email": email,
                "role": role,
                "scope_type": "workspace",
                "scope_id": str(workspace),
            },
        )
        assert response.status_code == 201, response.text
        return str(response.json()["token"])

    def accept(
        self,
        organization: UUID,
        token: str,
        subject: str = "invitee",
        email: str = "invitee@example.com",
    ) -> UUID:
        response = self.client.post(
            f"/api/v1/organizations/{organization}/invitations/accept",
            headers=self.headers(subject, email),
            json={"token": token},
        )
        assert response.status_code == 200, response.text
        return UUID(response.json()["id"])


@pytest.fixture
def api(signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    url = os.environ.get("IOP_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("Isolated test database required in CI")
        pytest.skip("Set IOP_TEST_DATABASE_URL")
    settings = configured(Settings(database_url=SecretStr(url)))  # type: ignore[call-arg]
    monkeypatch.setenv("IOP_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine(settings)
    with engine.connect() as connection:
        outer = connection.begin()
        sessions = sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        with sessions() as session:
            principal = Principal("https://identity.example.test", "platform")
            with session.begin():
                compose(session, principal).identity.bootstrap(principal, "test fixture operator")
            verifier = OidcVerifier(settings, Resolver(signing_key.public_key()))
            app = create_app(settings, verifier=verifier)
            try:
                with TestClient(app, client=(str(uuid7()), 50000)) as client:
                    app.state.sessions = sessions
                    yield Api(client, session, signing_key, settings)
            finally:
                session.close()
                outer.rollback()
    engine.dispose()


def test_platform_does_not_bypass_tenant_policy_and_cross_tenant_reads(api: Api) -> None:
    first = api.organization("admin")
    second = api.organization("other")
    workspace = api.workspace(first)
    for subject, organization, target in (
        ("platform", first, workspace),
        ("other", first, workspace),
        ("admin", second, workspace),
    ):
        response = api.client.get(
            f"/api/v1/organizations/{organization}/workspaces/{target}",
            headers=api.headers(subject),
        )
        assert response.status_code == 403
    me = api.client.get("/api/v1/me", headers=api.headers("admin"))
    assert me.status_code == 200
    assert [entry["organization_id"] for entry in me.json()["memberships"]] == [str(first)]


def test_domain_pack_api_enforces_tenant_scope_and_install_permission(api: Api) -> None:
    first = api.organization("pack-admin")
    second = api.organization("other-pack-admin")
    base = f"/api/v1/organizations/{first}/domain-packs"

    catalog = api.client.get(f"{base}/catalog", headers=api.headers("pack-admin"))
    assert catalog.status_code == 200
    assert catalog.json()["valid"] is True
    assert [item["manifest"]["id"] for item in catalog.json()["releases"]] == [
        "org.example.oil-gas"
    ]
    installations = api.client.get(f"{base}/installations", headers=api.headers("pack-admin"))
    assert installations.status_code == 200
    assert installations.json() == {"items": []}

    cross_tenant = api.client.get(
        f"/api/v1/organizations/{second}/domain-packs/installations",
        headers=api.headers("pack-admin"),
    )
    assert cross_tenant.status_code == 403

    token = api.invitation(
        first,
        api.workspace(first, "pack-admin"),
        "Viewer",
        "pack-admin",
        "pack-viewer@example.com",
    )
    api.accept(first, token, "pack-viewer", "pack-viewer@example.com")
    plan = api.client.post(
        f"{base}/plans",
        headers=api.headers("pack-viewer"),
        json={
            "operation": "install",
            "pack_id": "org.example.operations-basics",
            "version_range": "=1.0.0",
        },
    )
    assert plan.status_code == 403


def test_domain_pack_api_installs_reviewed_release_and_audits(api: Api, tmp_path: Path) -> None:
    organization = api.organization("pack-installer")
    pack_id = "org.example.operations-basics"
    release = tmp_path / pack_id / "1.0.0"
    release.mkdir(parents=True)
    content = b"Organization-neutral localization metadata\n"
    (release / "README.md").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema_version": "1",
        "id": pack_id,
        "name": "Operations Basics",
        "version": "1.0.0",
        "pack_type": "functional",
        "core_version_range": ">=0.1.0 <1.0.0",
        "dependencies": [],
        "capabilities": ["locales"],
        "content_checksums": [{"path": "README.md", "sha256": digest}],
        "publisher": "Platform Curators",
    }
    (release / "pack.yaml").write_text(json.dumps(manifest), encoding="utf-8")
    api.settings.domain_pack_registry_directory = str(tmp_path)
    base = f"/api/v1/organizations/{organization}/domain-packs"

    planned = api.client.post(
        f"{base}/plans",
        headers=api.headers("pack-installer"),
        json={"operation": "install", "pack_id": pack_id, "version_range": "=1.0.0"},
    )
    assert planned.status_code == 200, planned.text
    plan = planned.json()
    assert plan["valid"] is True
    assert plan["selected_release_summaries"][0]["content_sha256"]
    assert plan["selected_releases"] == []

    applied = api.client.post(
        f"{base}/apply",
        headers=api.headers("pack-installer"),
        json={
            "operation": "install",
            "pack_id": pack_id,
            "version_range": "=1.0.0",
            "expected_plan_sha256": plan["plan_sha256"],
            "reason": "Approved organization pack rollout",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["items"][0]["state"] == "installed"
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.organization_id == organization,
            AuditRow.type == "domain_pack.install",
        )
    )
    assert audit is not None
    assert audit.payload["pack_id"] == pack_id
    assert audit.payload["package_sha256"] == plan["steps"][0]["content_sha256"]


def test_domain_pack_migration_refuses_populated_rollback(api: Api, tmp_path: Path) -> None:
    organization = api.organization("pack-rollback-installer")
    pack_id = "org.example.rollback-check"
    release = tmp_path / pack_id / "1.0.0"
    release.mkdir(parents=True)
    content = b"Rollback guard fixture\n"
    (release / "README.md").write_bytes(content)
    manifest = {
        "schema_version": "1",
        "id": pack_id,
        "name": "Rollback Check",
        "version": "1.0.0",
        "pack_type": "functional",
        "core_version_range": ">=0.1.0 <1.0.0",
        "dependencies": [],
        "capabilities": ["locales"],
        "content_checksums": [{"path": "README.md", "sha256": hashlib.sha256(content).hexdigest()}],
        "publisher": "Platform Curators",
    }
    (release / "pack.yaml").write_text(json.dumps(manifest), encoding="utf-8")
    api.settings.domain_pack_registry_directory = str(tmp_path)
    base = f"/api/v1/organizations/{organization}/domain-packs"
    plan_response = api.client.post(
        f"{base}/plans",
        headers=api.headers("pack-rollback-installer"),
        json={"operation": "install", "pack_id": pack_id, "version_range": "=1.0.0"},
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    applied = api.client.post(
        f"{base}/apply",
        headers=api.headers("pack-rollback-installer"),
        json={
            "operation": "install",
            "pack_id": pack_id,
            "version_range": "=1.0.0",
            "expected_plan_sha256": plan["plan_sha256"],
            "reason": "Verify populated-history rollback protection",
        },
    )
    assert applied.status_code == 200, applied.text

    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("2ad7f8e6c301")
    assert revision is not None
    with pytest.raises(DBAPIError, match="Pack history prevents rollback"):  # noqa: SIM117
        with ExitStack() as stack:
            stack.enter_context(api.session.begin_nested())
            stack.enter_context(
                Operations.context(MigrationContext.configure(api.session.connection()))
            )
            revision.module.downgrade()
    installations = api.client.get(
        f"{base}/installations", headers=api.headers("pack-rollback-installer")
    )
    assert installations.status_code == 200


def test_invitation_replay_email_binding_revocation_and_history(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    token = api.invitation(organization, workspace)
    invite = api.session.scalar(
        select(InvitationRow).where(InvitationRow.organization_id == organization)
    )
    assert invite is not None and invite.token_digest != token
    wrong_email = api.client.post(
        f"/api/v1/organizations/{organization}/invitations/accept",
        headers=api.headers("attacker", "attacker@example.com"),
        json={"token": token},
    )
    assert wrong_email.status_code == 403
    user_id = api.accept(organization, token)
    route = f"/api/v1/organizations/{organization}/workspaces/{workspace}"
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 200
    assert (
        api.client.put(
            route,
            headers=api.headers("invitee"),
            json={
                "name": "Unauthorized",
                "expected_version": 1,
            },
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/invitations/accept",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"token": token},
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/users/{user_id}/revoke",
            headers=api.headers("admin"),
        ).status_code
        == 204
    )
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 403
    api.session.expire_all()
    user = api.session.get(UserRow, user_id)
    assert user is not None and not user.active
    grants = api.session.scalars(select(GrantRow).where(GrantRow.user_id == user_id)).all()
    assert grants and all(grant.revoked for grant in grants)
    accepted = api.session.scalars(
        select(AuditRow).where(AuditRow.type == "identity.invitation.accepted")
    )
    assert any(event.actor_id == user_id for event in accepted)
    restored = api.accept(organization, api.invitation(organization, workspace))
    assert restored == user_id
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 200


def test_scoped_managers_cannot_escalate_or_change_own_grants(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    second_workspace = api.workspace(organization)
    manager = api.accept(organization, api.invitation(organization, workspace, "WorkspaceAdmin"))
    own = api.client.post(
        f"/api/v1/organizations/{organization}/grants",
        headers=api.headers("invitee"),
        json={
            "user_id": str(manager),
            "role": "WorkspaceOwner",
            "scope_type": "workspace",
            "scope_id": str(workspace),
        },
    )
    assert own.status_code == 403
    elevated = api.client.post(
        f"/api/v1/organizations/{organization}/invitations",
        headers=api.headers("invitee"),
        json={
            "email": "new@example.com",
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(organization),
        },
    )
    assert elevated.status_code == 403
    assert (
        api.client.get(
            f"/api/v1/organizations/{organization}/workspaces/{second_workspace}",
            headers=api.headers("invitee"),
        ).status_code
        == 403
    )
    delegated = api.invitation(organization, workspace, subject="invitee", email="new@example.com")
    api.accept(organization, delegated, "new", "new@example.com")


def test_optimistic_concurrency_mass_assignment_and_suspension(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    route = f"/api/v1/organizations/{organization}/workspaces/{workspace}"
    changed = api.client.put(
        route, headers=api.headers("admin"), json={"name": "Updated", "expected_version": 1}
    )
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert (
        api.client.put(
            route, headers=api.headers("admin"), json={"name": "Stale", "expected_version": 1}
        ).status_code
        == 409
    )
    assert (
        api.client.put(
            route,
            headers=api.headers("admin"),
            json={
                "name": "Bad",
                "expected_version": 2,
                "organization_id": str(uuid7()),
            },
        ).status_code
        == 422
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/suspend",
            headers=api.headers(),
            json={"reason": "Operational suspension"},
        ).status_code
        == 204
    )
    assert api.client.get(route, headers=api.headers("admin")).status_code == 403
    assert (
        api.client.post(
            f"/api/v1/organizations/{organization}/resume",
            headers=api.headers(),
            json={"reason": "Recovery verified"},
        ).status_code
        == 204
    )
    assert api.client.get(route, headers=api.headers("admin")).status_code == 200


def test_audit_mutations_and_populated_migration_rollback_are_rejected(api: Api) -> None:
    api.organization()
    for statement in (
        "UPDATE audit_events SET type = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(statement))
    config = Config("alembic.ini")
    # A separate connection cannot see fixture savepoints; inspect guard using
    # Alembic's MigrationContext on the transaction holding the real rows.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    revision = ScriptDirectory.from_config(config).get_revision("34c1f0cc7d24")
    assert revision is not None
    with (
        Operations.context(MigrationContext.configure(api.session.connection())),
        pytest.raises(RuntimeError, match="Refusing populated"),
    ):
        revision.module.downgrade()


def test_atomic_audit_failure_rolls_back_business_write(api: Api) -> None:
    class BrokenAudit:
        def append(self, event: object) -> None:
            raise RuntimeError("audit unavailable")

    from operations.modules.identity.application.contracts import RequestContext
    from operations.modules.organizations.application.contracts import OrganizationSettings
    from operations.modules.organizations.application.service import OrganizationService

    services = compose(api.session)
    service = OrganizationService(
        services.organizations.store,
        services.identity.store,
        services.authorization.grants,
        services.authorization,
        BrokenAudit(),
    )
    context = RequestContext(
        Principal("https://identity.example.test", "platform"), uuid7(), uuid7()
    )
    with pytest.raises(RuntimeError), api.session.begin_nested():
        service.create(
            context, "Should rollback", OrganizationSettings(), "temporary", "t@example.com"
        )
    assert (
        api.session.scalar(select(OrganizationRow).where(OrganizationRow.name == "Should rollback"))
        is None
    )


def test_expired_and_revoked_inviter_tokens_fail(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    token = api.invitation(organization, workspace)
    with patch("operations.modules.identity.application.service.datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime.now(UTC) + timedelta(days=8)
        response = api.client.post(
            f"/api/v1/organizations/{organization}/invitations/accept",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"token": token},
        )
    assert response.status_code == 403
    manager = api.accept(organization, api.invitation(organization, workspace, "WorkspaceAdmin"))
    pending = api.invitation(organization, workspace, subject="invitee", email="new@example.com")
    api.client.post(
        f"/api/v1/organizations/{organization}/users/{manager}/revoke", headers=api.headers("admin")
    )
    response = api.client.post(
        f"/api/v1/organizations/{organization}/invitations/accept",
        headers=api.headers("new", "new@example.com"),
        json={"token": pending},
    )
    assert response.status_code == 403


def test_domain_pack_artifact_import_is_preview_bound_audited_and_idempotent(api: Api) -> None:
    organization = api.organization("phase9-pack-admin")
    workspace = api.workspace(organization, "phase9-pack-admin")
    base = f"/api/v1/organizations/{organization}/domain-packs"
    headers = api.headers("phase9-pack-admin")

    plan = api.client.post(
        f"{base}/plans",
        headers=headers,
        json={"operation": "install", "pack_id": "org.example.oil-gas", "version_range": "=1.0.0"},
    )
    assert plan.status_code == 200, plan.text
    applied = api.client.post(
        f"{base}/apply",
        headers=headers,
        json={
            "operation": "install",
            "pack_id": "org.example.oil-gas",
            "version_range": "=1.0.0",
            "expected_plan_sha256": plan.json()["plan_sha256"],
            "reason": "Review the curated starter templates",
            "confirm_breaking_change": False,
        },
    )
    assert applied.status_code == 200, applied.text

    artifacts = api.client.get(
        f"{base}/catalog/org.example.oil-gas/1.0.0/artifacts", headers=headers
    )
    assert artifacts.status_code == 200, artifacts.text
    form_artifact = next(
        item for item in artifacts.json()["items"] if item["artifact_id"] == "daily-drilling-report"
    )
    request = {
        "pack_id": "org.example.oil-gas",
        "pack_version": "1.0.0",
        "artifact_id": form_artifact["artifact_id"],
        "artifact_version": form_artifact["artifact_version"],
        "workspace_id": str(workspace),
        "idempotency_key": str(uuid7()),
    }
    preview = api.client.post(f"{base}/imports/preview", headers=headers, json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid"] is True

    apply_body = {**request, "expected_preview_sha256": preview.json()["preview_sha256"]}
    imported = api.client.post(f"{base}/imports", headers=headers, json=apply_body)
    assert imported.status_code == 200, imported.text
    replay = api.client.post(f"{base}/imports", headers=headers, json=apply_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == imported.json()["id"]

    forms = api.client.get(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/forms", headers=headers
    )
    assert forms.status_code == 200
    created = next(
        item for item in forms.json()["items"] if item["id"] == imported.json()["target_id"]
    )
    version = api.client.get(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/forms/{created['id']}/versions/1",
        headers=headers,
    )
    assert version.status_code == 200
    assert version.json()["state"] == "draft"
    audit = api.session.scalar(
        select(AuditRow).where(
            AuditRow.organization_id == organization,
            AuditRow.aggregate_id == UUID(created["id"]),
            AuditRow.type == "form.created",
        )
    )
    assert audit is not None
    assert audit.payload["pack_id"] == "org.example.oil-gas"
    assert audit.payload["pack_artifact_id"] == "daily-drilling-report"
    assert audit.payload["package_sha256"] == applied.json()["items"][0]["content_sha256"]

    # Workspace imports cross the owning module services and remain drafts.
    master_data_artifact = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "rig" and item["kind"] == "master_data_type"
    )
    master_data_request = {
        **request,
        "artifact_id": master_data_artifact["artifact_id"],
        "artifact_version": master_data_artifact["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    md_preview = api.client.post(
        f"{base}/imports/preview", headers=headers, json=master_data_request
    )
    assert md_preview.status_code == 200, md_preview.text
    md_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **master_data_request,
            "expected_preview_sha256": md_preview.json()["preview_sha256"],
        },
    )
    assert md_import.status_code == 200, md_import.text
    assert md_import.json()["artifact_kind"] == "master_data_type"

    project_response = api.client.post(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/projects",
        headers=headers,
        json={"name": "Pack import project"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    project_request = {
        **master_data_request,
        "project_id": project_id,
        "idempotency_key": str(uuid7()),
    }
    project_preview = api.client.post(
        f"{base}/imports/preview", headers=headers, json=project_request
    )
    assert project_preview.status_code == 200, project_preview.text
    project_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **project_request,
            "expected_preview_sha256": project_preview.json()["preview_sha256"],
        },
    )
    assert project_import.status_code == 200, project_import.text
    assert project_import.json()["project_id"] == project_id

    operations_form = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "daily-operations-report" and item["kind"] == "form"
    )
    operations_form_request = {
        **request,
        "artifact_id": operations_form["artifact_id"],
        "artifact_version": operations_form["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    operations_form_preview = api.client.post(
        f"{base}/imports/preview", headers=headers, json=operations_form_request
    )
    assert operations_form_preview.status_code == 200, operations_form_preview.text
    operations_form_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **operations_form_request,
            "expected_preview_sha256": operations_form_preview.json()["preview_sha256"],
        },
    )
    assert operations_form_import.status_code == 200, operations_form_import.text

    workflow_artifact = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "supervisor-approval" and item["kind"] == "workflow"
    )
    workflow_request = {
        **request,
        "artifact_id": workflow_artifact["artifact_id"],
        "artifact_version": workflow_artifact["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    workflow_preview = api.client.post(
        f"{base}/imports/preview", headers=headers, json=workflow_request
    )
    assert workflow_preview.status_code == 200, workflow_preview.text
    workflow_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **workflow_request,
            "expected_preview_sha256": workflow_preview.json()["preview_sha256"],
        },
    )
    assert workflow_import.status_code == 200, workflow_import.text
    workflows = api.client.get(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/workflows", headers=headers
    )
    assert workflows.status_code == 200
    workflow_id = workflow_import.json()["target_id"]
    created_workflow = next(item for item in workflows.json()["items"] if item["id"] == workflow_id)
    workflow_versions = api.client.get(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/workflows/{created_workflow['id']}/versions",
        headers=headers,
    )
    assert workflow_versions.status_code == 200
    assert workflow_versions.json()["items"][0]["state"] == "draft"

    publish_url = (
        f"/api/v1/organizations/{organization}/workspaces/{workspace}"
        f"/forms/{created['id']}/versions/1/publish"
    )
    publication_preview = api.client.post(
        publish_url, headers=headers, json={"expected_revision": 1}
    )
    assert publication_preview.status_code == 200, publication_preview.text
    published = api.client.post(
        publish_url,
        headers=headers,
        json={
            "expected_revision": 1,
            "dry_run": False,
            "expected_sha256": publication_preview.json()["content_sha256"],
        },
    )
    assert published.status_code == 200, published.text

    submission_created = api.client.post(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/submissions",
        headers=headers,
        json={"form_id": created["id"], "number": 1},
    )
    assert submission_created.status_code == 201, submission_created.text
    submission_id = submission_created.json()["id"]
    submission_url = (
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/submissions/{submission_id}"
    )
    saved_submission = api.client.put(
        submission_url,
        headers=headers,
        json={
            "expected_revision": 1,
            "values": {
                "fields": {
                    "report_date": datetime.now(UTC).date().isoformat(),
                    "well_name": "well-a",
                    "rop": "4.5",
                }
            },
        },
    )
    assert saved_submission.status_code == 200, saved_submission.text
    submitted = api.client.post(
        f"{submission_url}/submit",
        headers=headers,
        json={"expected_revision": 2, "idempotency_key": str(uuid7()), "reason": "Reviewed"},
    )
    assert submitted.status_code == 200, submitted.text

    kpi_artifact = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "rop-average" and item["kind"] == "kpi"
    )
    kpi_request = {
        **request,
        "artifact_id": kpi_artifact["artifact_id"],
        "artifact_version": kpi_artifact["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    kpi_preview = api.client.post(f"{base}/imports/preview", headers=headers, json=kpi_request)
    assert kpi_preview.status_code == 200, kpi_preview.text
    kpi_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **kpi_request,
            "expected_preview_sha256": kpi_preview.json()["preview_sha256"],
        },
    )
    assert kpi_import.status_code == 200, kpi_import.text
    reports_url = f"/api/v1/organizations/{organization}/workspaces/{workspace}/reports"
    kpi_report_id = kpi_import.json()["target_id"]
    kpi_definition = api.client.get(f"{reports_url}/saved/{kpi_report_id}", headers=headers)
    assert kpi_definition.status_code == 200, kpi_definition.text
    saved_kpi = kpi_definition.json()["definition"]["kpi"]
    assert saved_kpi["source_form"] == created["id"]
    assert saved_kpi["source_form_number"] == 1
    kpi_run = api.client.get(f"{reports_url}/saved/{kpi_report_id}/run", headers=headers)
    assert kpi_run.status_code == 200, kpi_run.text
    assert kpi_run.json()["kpi_result"]["unit"] == "length/hour"
    assert kpi_run.json()["kpi_result"]["groups"] == [{"group": "well-a", "value": 4.5}]
    dashboard = api.client.post(
        f"{reports_url}/dashboards",
        headers=headers,
        json={
            "name": "Private drilling KPIs",
            "definition": {
                "widgets": [{"report_id": kpi_report_id, "kind": "bar", "title": "ROP by well"}]
            },
        },
    )
    assert dashboard.status_code == 201, dashboard.text
    dashboard_run = api.client.get(
        f"{reports_url}/dashboards/{dashboard.json()['id']}/run", headers=headers
    )
    assert dashboard_run.status_code == 200, dashboard_run.text
    assert dashboard_run.json()["widgets"][0]["report"]["kpi_result"]["unit"] == "length/hour"
    assert dashboard_run.json()["widgets"][0]["report"]["kpi_result"]["groups"][0]["value"] == 4.5

    inert_artifact = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "npt-investigation-task" and item["kind"] == "automation_template"
    )
    inert_request = {
        **request,
        "artifact_id": inert_artifact["artifact_id"],
        "artifact_version": inert_artifact["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    inert_preview = api.client.post(f"{base}/imports/preview", headers=headers, json=inert_request)
    assert inert_preview.status_code == 200, inert_preview.text
    inert_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **inert_request,
            "expected_preview_sha256": inert_preview.json()["preview_sha256"],
        },
    )
    assert inert_import.status_code == 200, inert_import.text
    assert inert_import.json()["inert_definition"]["trigger"] == "task.overdue"
    rules = api.client.get(
        f"/api/v1/organizations/{organization}/workspaces/{workspace}/automation-rules",
        headers=headers,
    )
    assert rules.status_code == 200, rules.text
    assert rules.json()["items"] == []

    mapping_artifact = next(
        item
        for item in artifacts.json()["items"]
        if item["artifact_id"] == "well-to-site" and item["kind"] == "mapping_profile"
    )
    mapping_request = {
        **request,
        "artifact_id": mapping_artifact["artifact_id"],
        "artifact_version": mapping_artifact["artifact_version"],
        "idempotency_key": str(uuid7()),
    }
    mapping_preview = api.client.post(
        f"{base}/imports/preview", headers=headers, json=mapping_request
    )
    assert mapping_preview.status_code == 200, mapping_preview.text
    mapping_import = api.client.post(
        f"{base}/imports",
        headers=headers,
        json={
            **mapping_request,
            "expected_preview_sha256": mapping_preview.json()["preview_sha256"],
        },
    )
    assert mapping_import.status_code == 200, mapping_import.text
    assert mapping_import.json()["inert_definition"]["target_kind"] == "internal.site.v1"

    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("b6c712a9f3e1")
    assert revision is not None
    with (
        pytest.raises(DBAPIError, match="Pack import history prevents rollback"),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()


def test_database_composite_fk_rejects_cross_tenant_grants(api: Api) -> None:
    first = api.organization()
    second = api.organization("other")
    workspace = api.workspace(first)
    target = api.session.scalar(select(UserRow).where(UserRow.organization_id == second))
    assert target is not None
    with pytest.raises(IntegrityError), api.session.begin_nested():
        api.session.add(
            GrantRow(
                id=uuid7(),
                organization_id=first,
                user_id=target.id,
                role="Viewer",
                scope_type="workspace",
                scope_id=workspace,
                workspace_id=workspace,
                inherit=False,
                revoked=False,
                valid_from=None,
                valid_until=None,
            )
        )
        api.session.flush()


def test_authentication_failure_is_audited_and_token_not_stored(api: Api) -> None:
    response = api.client.get(
        "/api/v1/me", headers={"Authorization": "Bearer secret-invalid-token"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    event = api.session.scalar(
        select(AuditRow).where(AuditRow.type == "identity.authentication.failed")
    )
    assert event is not None
    assert "secret-invalid-token" not in str(event.payload)


def test_bearer_only_and_rate_limit_fail_closed(api: Api) -> None:
    token = access_token(api.key)
    assert api.client.get("/api/v1/me", params={"access_token": token}).status_code == 401
    api.client.cookies.set("access_token", token)
    assert api.client.get("/api/v1/me").status_code == 401
    api.client.app.state.limiter.maximum = 3  # type: ignore[attr-defined]
    assert api.client.get("/api/v1/me", headers=api.headers()).status_code == 200
    response = api.client.get("/api/v1/me", headers=api.headers())
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"


def test_workspace_listing_respects_explicit_scope_and_archive(api: Api) -> None:
    organization = api.organization()
    workspace = api.workspace(organization)
    api.workspace(organization)
    api.accept(organization, api.invitation(organization, workspace))
    route = f"/api/v1/organizations/{organization}/workspaces"
    visible = api.client.get(route, headers=api.headers("invitee")).json()
    assert [item["id"] for item in visible["items"]] == [str(workspace)]
    assert visible["next_cursor"] is None
    assert (
        api.client.put(
            f"{route}/{workspace}",
            headers=api.headers("admin"),
            json={"name": "Archived", "active": False, "expected_version": 1},
        ).status_code
        == 200
    )
    assert api.client.get(f"{route}/{workspace}", headers=api.headers("invitee")).status_code == 404
    assert api.client.get(route, headers=api.headers("invitee")).json()["items"] == []


def test_organization_settings_and_admin_delegation_are_audited(api: Api) -> None:
    organization = api.organization()
    route = f"/api/v1/organizations/{organization}"
    body = {
        "name": "Configured tenant",
        "expected_version": 1,
        "settings": {
            "locale": "fa-IR",
            "timezone": "Asia/Tehran",
            "unit_system": "SI",
            "brand_name": "Tenant brand",
        },
    }
    assert api.client.put(route, headers=api.headers(), json=body).status_code == 403
    changed = api.client.put(route, headers=api.headers("admin"), json=body)
    assert changed.status_code == 200 and changed.json()["settings"] == body["settings"]
    assert api.client.put(route, headers=api.headers("admin"), json=body).status_code == 409
    for timezone in ("Unknown/Timezone", "/etc/passwd"):
        invalid = {**body, "expected_version": 2, "settings": {"timezone": timezone}}
        assert api.client.put(route, headers=api.headers("admin"), json=invalid).status_code == 422
    invitation = api.client.post(
        f"{route}/invitations",
        headers=api.headers("admin"),
        json={
            "email": "second@example.com",
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(organization),
        },
    )
    assert invitation.status_code == 201
    user_id = api.accept(organization, invitation.json()["token"], "second", "second@example.com")
    assert api.client.get(route, headers=api.headers("second")).status_code == 200
    events = api.session.scalars(
        select(AuditRow).where(AuditRow.organization_id == organization)
    ).all()
    assert any(event.type == "organization.updated" for event in events)
    delegated = next(
        event for event in events if event.type == "iam.grant.created" and event.actor_id == user_id
    )
    assert delegated.actor_subject == "second" and delegated.payload["authorized_by"]
