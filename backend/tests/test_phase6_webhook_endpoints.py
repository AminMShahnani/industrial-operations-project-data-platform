from uuid import UUID

import pytest
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.integrations.infrastructure.persistence import WebhookEndpointRow
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api

pytestmark = pytest.mark.integration


def test_endpoint_versions_are_scoped_immutable_audited_and_hide_secret_refs(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    base = f"/api/v1/organizations/{org}/webhook-endpoints"
    headers = api.headers("admin")
    created = api.client.post(
        base,
        headers=headers,
        params={"workspace_id": str(workspace)},
        json={
            "name": "Operations receiver",
            "url": "https://hooks.example.test/v1/events",
            "secret_reference": "tenant/webhooks/ops/key-v1",
            "signing_key_version": 1,
        },
    )
    assert created.status_code == 201, created.text
    first = created.json()
    endpoint_id = UUID(first["endpoint_id"])
    assert first["version"] == 1 and first["secret_reference_present"] is True
    assert "secret_reference" not in first

    changed = api.client.post(
        f"{base}/{endpoint_id}/versions",
        headers=headers,
        json={
            "expected_version": 1,
            "name": "Operations receiver",
            "url": "https://hooks2.example.test/v1/events",
            "secret_reference": "tenant/webhooks/ops/key-v2",
            "signing_key_version": 2,
        },
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["version"] == 2
    assert changed.json()["signing_key_version"] == 2
    assert changed.json()["url"] == "https://hooks2.example.test/v1/events"
    stale = api.client.post(
        f"{base}/{endpoint_id}/versions",
        headers=headers,
        json={
            "expected_version": 1,
            "name": "stale update",
            "url": "https://hooks3.example.test/events",
            "secret_reference": "tenant/webhooks/ops/key-v3",
            "signing_key_version": 3,
        },
    )
    assert stale.status_code == 409

    revoked = api.client.post(
        f"{base}/{endpoint_id}/revoke",
        headers=headers,
        json={"expected_version": 2, "reason": "Receiver retired"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["version"] == 3 and revoked.json()["state"] == "revoked"
    blocked = api.client.post(
        f"{base}/{endpoint_id}/versions",
        headers=headers,
        json={
            "expected_version": 3,
            "name": "cannot reopen",
            "url": "https://hooks.example.test/events",
            "secret_reference": "tenant/webhooks/ops/key-v4",
            "signing_key_version": 4,
        },
    )
    assert blocked.status_code == 409

    old_version = api.client.get(f"{base}/{endpoint_id}/versions/1", headers=headers)
    assert old_version.status_code == 200 and old_version.json()["version"] == 1
    listed = api.client.get(base, headers=headers, params={"workspace_id": str(workspace)})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["version"] == 3

    rows = list(
        api.session.scalars(
            select(WebhookEndpointRow)
            .where(WebhookEndpointRow.organization_id == org)
            .order_by(WebhookEndpointRow.version)
        )
    )
    assert [row.version for row in rows] == [1, 2, 3]
    for row in rows:
        audit = api.session.get(AuditRow, row.audit_id)
        assert audit is not None
        assert audit.aggregate_id == endpoint_id
        assert audit.actor_id == row.created_by_id
        assert audit.payload["target_id"] == str(endpoint_id)
        assert audit.payload["version"] == row.version
        assert audit.payload["signing_key_version"] == row.signing_key_version
        assert row.secret_reference not in str(audit.payload)
    with pytest.raises(DBAPIError, match="immutable"), api.session.begin_nested():
        api.session.execute(
            text("UPDATE webhook_endpoint_versions SET name='tampered' WHERE audit_id=:id"),
            {"id": rows[0].audit_id},
        )


def test_endpoint_scope_authority_and_url_policy_are_server_enforced(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    base = f"/api/v1/organizations/{org}/webhook-endpoints"
    invite = api.invitation(org, workspace, role="Viewer")
    api.accept(org, invite)
    viewer = api.headers("invitee", "invitee@example.com")
    assert (
        api.client.post(
            base,
            headers=viewer,
            params={"workspace_id": str(workspace)},
            json={
                "name": "Denied",
                "url": "https://hooks.example.test/events",
                "secret_reference": "tenant/webhooks/key-1",
                "signing_key_version": 1,
            },
        ).status_code
        == 403
    )
    for url in (
        "http://hooks.example.test/events",
        "https://user:password@hooks.example.test/events",
        "https://hooks.example.test/events?token=secret",
        "https://hooks.example.test/events#fragment",
    ):
        response = api.client.post(
            base,
            headers=api.headers("admin"),
            params={"workspace_id": str(workspace)},
            json={
                "name": "Invalid URL",
                "url": url,
                "secret_reference": "tenant/webhooks/key-1",
                "signing_key_version": 1,
            },
        )
        assert response.status_code == 422
