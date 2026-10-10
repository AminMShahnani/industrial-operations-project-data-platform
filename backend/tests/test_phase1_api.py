import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
from alembic import command
from alembic.config import Config
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
                    yield Api(client, session, signing_key)
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
