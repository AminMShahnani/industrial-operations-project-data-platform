from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.modules.audit.application.contracts import AuditEvent
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.infrastructure.persistence import InvitationRow
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from test_oidc import access_token
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api

pytestmark = pytest.mark.integration


def create(api: Api, org: UUID, workspace: UUID, identifier: UUID | None = None) -> UUID:
    identifier = identifier or uuid7()
    response = api.client.post(
        f"/api/v1/organizations/{org}/invitations/verified-email",
        headers=api.headers("admin"),
        json={
            "id": str(identifier),
            "email": "INVITEE@example.com",
            "role": "Viewer",
            "scope_type": "workspace",
            "scope_id": str(workspace),
        },
    )
    assert response.status_code == 201, response.text
    assert set(response.json()) == {"id", "organization_id", "expires_at"}
    return UUID(response.json()["id"])


def accept_route(org: UUID, identifier: UUID) -> str:
    return f"/api/v1/organizations/{org}/invitations/verified-email/{identifier}/accept"


def test_verified_email_lifecycle_secret_free_retry_and_token_separation(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    legacy_token = api.invitation(org, workspace, email="legacy@example.com")
    legacy = api.session.scalar(select(InvitationRow).where(InvitationRow.organization_id == org))
    assert legacy and legacy.acceptance_mode == "token" and legacy.token_digest
    identifier = create(api, org, workspace)
    assert create(api, org, workspace, identifier) == identifier
    invitation = api.session.get(InvitationRow, identifier)
    assert invitation and invitation.token_digest is None
    assert invitation.acceptance_mode == "verified_email"
    assert invitation.email == "invitee@example.com"
    assert invitation.expires_at > datetime.now(UTC) + timedelta(days=6)
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(AuditRow)
            .where(
                AuditRow.type == "identity.invitation.email_created",
                AuditRow.aggregate_id == identifier,
            )
        )
        == 1
    )
    assert (
        api.client.post(
            accept_route(org, legacy.id), headers=api.headers("legacy", "legacy@example.com")
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/invitations/accept",
            headers=api.headers("invitee", "invitee@example.com"),
            json={"token": str(identifier) + "xxxx"},
        ).status_code
        == 403
    )
    route = accept_route(org, identifier)
    assert api.client.get(route, headers=api.headers("invitee")).status_code == 405
    response = api.client.post(route, headers=api.headers("invitee", "invitee@example.com"))
    assert response.status_code == 200, response.text
    user = UUID(response.json()["id"])
    assert (
        api.client.post(route, headers=api.headers("invitee", "invitee@example.com")).status_code
        == 403
    )
    assert (
        api.session.scalar(
            select(func.count())
            .select_from(GrantRow)
            .where(GrantRow.organization_id == org, GrantRow.user_id == user)
        )
        == 1
    )
    assert api.accept(org, legacy_token, "legacy", "legacy@example.com") != user
    evidence = api.session.scalars(
        select(AuditRow).where(AuditRow.aggregate_id == identifier)
    ).all()
    assert len(evidence) == 2
    for event in evidence:
        assert "invitee@example.com" not in str(event.payload)
        assert legacy_token not in str(event.payload)
    # Acceptance is monotonic and its immutable security binding cannot be retargeted.
    for values in (
        {"accepted_at": None},
        {"email": "other@example.com"},
        {"acceptance_mode": "token", "token_digest": "0" * 64},
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(
                update(InvitationRow).where(InvitationRow.id == identifier).values(**values)
            )
    for statement in ("DELETE FROM invitations WHERE id = :id", "TRUNCATE invitations"):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(statement), {"id": identifier})


@pytest.mark.parametrize(
    "email,verified",
    [
        ("other@example.com", True),
        ("invitee@example.com", False),
        (None, True),
    ],
)
def test_accept_requires_oidc_verified_matching_email(
    api: Api, email: str | None, verified: bool
) -> None:
    org = api.organization()
    identifier = create(api, org, api.workspace(org))
    token = access_token(api.key, "invitee", email=email, email_verified=verified)
    route = accept_route(org, identifier)
    assert api.client.post(route).status_code == 401
    assert api.client.post(route, headers={"Authorization": "Bearer " + token}).status_code == 403
    assert api.session.get(InvitationRow, identifier).accepted_at is None  # type: ignore[union-attr]


def test_creation_scope_and_request_reuse_fail_closed(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    other = api.organization("other")
    identifier = create(api, org, workspace)
    body = {
        "id": str(identifier),
        "email": "other@example.com",
        "role": "Viewer",
        "scope_type": "workspace",
        "scope_id": str(workspace),
    }
    route = f"/api/v1/organizations/{org}/invitations/verified-email"
    assert api.client.post(route, headers=api.headers("admin"), json=body).status_code == 409
    body["email"] = "invitee@example.com"
    assert api.client.post(route, headers=api.headers("platform"), json=body).status_code == 403
    assert api.client.post(route, headers=api.headers("other"), json=body).status_code == 403
    body["scope_id"] = str(api.workspace(other, "other"))
    assert api.client.post(route, headers=api.headers("admin"), json=body).status_code == 404
    body["scope_id"] = str(workspace)
    body["id"] = str(uuid4())
    assert api.client.post(route, headers=api.headers("admin"), json=body).status_code == 422
    assert (
        api.client.post(
            accept_route(other, identifier), headers=api.headers("invitee", "invitee@example.com")
        ).status_code
        == 403
    )


def test_expiry_and_current_target_activity(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = create(api, org, workspace)
    route = accept_route(org, identifier)
    with patch("operations.modules.identity.application.service.datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime.now(UTC) + timedelta(days=8)
        assert (
            api.client.post(
                route, headers=api.headers("invitee", "invitee@example.com")
            ).status_code
            == 403
        )
    assert (
        api.client.put(
            f"/api/v1/organizations/{org}/workspaces/{workspace}",
            headers=api.headers("admin"),
            json={"name": "Workspace", "active": False, "expected_version": 1},
        ).status_code
        == 200
    )
    assert (
        api.client.post(route, headers=api.headers("invitee", "invitee@example.com")).status_code
        == 404
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/suspend",
            headers=api.headers(),
            json={"reason": "Test suspension"},
        ).status_code
        == 204
    )
    assert (
        api.client.post(route, headers=api.headers("invitee", "invitee@example.com")).status_code
        == 403
    )


def test_revoked_inviter_grant_cannot_authorize_acceptance_or_retry(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    inviter = api.accept(org, api.invitation(org, workspace, "WorkspaceAdmin"))
    identifier = uuid7()
    body = {
        "id": str(identifier),
        "email": "new@example.com",
        "role": "Viewer",
        "scope_type": "workspace",
        "scope_id": str(workspace),
    }
    route = f"/api/v1/organizations/{org}/invitations/verified-email"
    assert api.client.post(route, headers=api.headers("invitee"), json=body).status_code == 201
    grant = api.session.scalar(select(GrantRow).where(GrantRow.user_id == inviter))
    assert grant
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/grants/{grant.id}/revoke", headers=api.headers("admin")
        ).status_code
        == 204
    )
    assert api.client.post(route, headers=api.headers("invitee"), json=body).status_code == 403
    assert (
        api.client.post(
            accept_route(org, identifier), headers=api.headers("new", "new@example.com")
        ).status_code
        == 403
    )


def test_populated_rollback_refuses_without_touching_history(api: Api) -> None:
    org = api.organization()
    identifier = create(api, org, api.workspace(org))
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("e18c49c4be63")
    assert revision
    with (
        pytest.raises(RuntimeError, match="history exists"),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()
    assert api.session.get(InvitationRow, identifier)
    assert (
        api.client.post(
            accept_route(org, identifier), headers=api.headers("invitee", "invitee@example.com")
        ).status_code
        == 200
    )


def test_token_only_migration_rollback_preserves_existing_invitation(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    token = api.invitation(org, workspace)
    original = api.session.scalar(select(InvitationRow).where(InvitationRow.organization_id == org))
    assert original
    expected = (original.id, original.token_digest, original.expires_at, original.accepted_at)
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("e18c49c4be63")
    assert revision
    with (
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()
        preserved = api.session.execute(
            text(
                "SELECT id, token_digest, expires_at, accepted_at FROM invitations WHERE id = :id"
            ),
            {"id": original.id},
        ).one()
        assert tuple(preserved) == expected
        revision.module.upgrade()
    assert api.accept(org, token)


def test_failed_audit_rolls_back_invitation_creation(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    identifier = uuid7()
    original = AuditedEventBus.append

    def fail(self: AuditedEventBus, event: AuditEvent) -> None:
        if event.type == "identity.invitation.email_created":
            raise RuntimeError("Injected audit failure")
        original(self, event)

    with monkeypatch.context() as scoped:
        scoped.setattr(AuditedEventBus, "append", fail)
        response = api.client.post(
            f"/api/v1/organizations/{org}/invitations/verified-email",
            headers=api.headers("admin"),
            json={
                "id": str(identifier),
                "email": "invitee@example.com",
                "role": "Viewer",
                "scope_type": "workspace",
                "scope_id": str(workspace),
            },
        )
        assert response.status_code == 500 and response.json()["code"] == "internal_error"
        assert "Injected audit failure" not in response.text
    assert api.session.get(InvitationRow, identifier) is None
    assert create(api, org, workspace, identifier) == identifier


def test_org_invitation_and_inactive_inviter(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    administrator = api.accept(org, api.invitation(org, workspace, "Viewer"))
    identifier = uuid7()
    response = api.client.post(
        f"/api/v1/organizations/{org}/invitations/verified-email",
        headers=api.headers("admin"),
        json={
            "id": str(identifier),
            "email": "new@example.com",
            "role": "OrganizationAdmin",
            "scope_type": "organization",
            "scope_id": str(org),
        },
    )
    assert response.status_code == 201
    assert (
        api.client.post(
            accept_route(org, identifier), headers=api.headers("new", "NEW@example.com")
        ).status_code
        == 200
    )
    assert (
        api.client.get(f"/api/v1/organizations/{org}", headers=api.headers("new")).status_code
        == 200
    )
    # Create with a delegated workspace administrator, then revoke the identity.
    manager = api.accept(
        org,
        api.invitation(org, workspace, "WorkspaceAdmin", email="manager@example.com"),
        "manager",
        "manager@example.com",
    )
    pending = uuid7()
    body = {
        "id": str(pending),
        "email": "future@example.com",
        "role": "Viewer",
        "scope_type": "workspace",
        "scope_id": str(workspace),
    }
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/invitations/verified-email",
            headers=api.headers("manager"),
            json=body,
        ).status_code
        == 201
    )
    assert (
        api.client.post(
            f"/api/v1/organizations/{org}/users/{manager}/revoke", headers=api.headers("admin")
        ).status_code
        == 204
    )
    assert (
        api.client.post(
            accept_route(org, pending), headers=api.headers("future", "future@example.com")
        ).status_code
        == 403
    )
    assert administrator != manager
