from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

import pytest
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRepository, AuditRow
from operations.modules.automation.application.contracts import RuleDefinition, WebhookAction
from operations.modules.automation.application.events import DeliveryMessage, OperationalEvent
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import AutomationRepository
from operations.modules.integrations.application.contracts import EndpointCreate
from operations.modules.integrations.application.delivery import WebhookDeliveryService
from operations.modules.integrations.application.webhooks import (
    UnconfiguredTenantSecretResolver,
    WebhookTransport,
)
from operations.modules.integrations.infrastructure.persistence import (
    WebhookAttemptRow,
    WebhookDeliveryRepository,
    WebhookDeliveryStateRow,
    WebhookEndpointRepository,
    WebhookIntentRow,
)
from operations.webhook_worker import process_webhook
from operations.worker import process_automation
from sqlalchemy import select
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase6_actions import activate, context

pytestmark = pytest.mark.integration


def test_webhook_intent_action_creates_audited_pending_delivery_atomically(api: Api) -> None:
    org = api.organization()
    workspace = api.workspace(org)
    project_id = UUID(project(api, org, workspace))
    actor, user_id = context(api, org)
    endpoint = compose(api.session).webhook_endpoints.create(
        actor,
        org,
        workspace,
        project_id,
        EndpointCreate(
            name="Delivery integration test",
            url="https://hooks.example.test/events",
            secret_reference="tenant/webhooks/integration-test/key-v1",
            signing_key_version=1,
        ),
    )
    endpoint_id = endpoint.endpoint_id
    activate(
        api,
        actor,
        org,
        workspace,
        project_id,
        RuleDefinition(
            trigger="integration.event",
            actions=[
                WebhookAction(kind="call_webhook", endpoint_id=endpoint_id, endpoint_version=1)
            ],
        ),
    )
    event = OperationalEvent(
        id=uuid7(),
        type="integration.event",
        occurred_at=datetime.now(UTC),
        organization_id=org,
        workspace_id=workspace,
        project_id=project_id,
        actor_id=user_id,
        correlation_id=actor.correlation_id,
        aggregate_type="integration",
        aggregate_id=uuid7(),
    )
    compose(api.session).automation.capture(event)
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(event.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    assert process_automation(api.session, message).state == "completed"

    intents = list(
        api.session.scalars(
            select(WebhookIntentRow).where(
                WebhookIntentRow.organization_id == org,
                WebhookIntentRow.event_id == event.id,
            )
        )
    )
    assert len(intents) == 1
    intent = intents[0]
    state = api.session.get(WebhookDeliveryStateRow, (intent.id, org))
    assert state and state.status == "pending" and state.attempts == 0
    assert (
        api.session.scalar(
            select(WebhookAttemptRow).where(
                WebhookAttemptRow.organization_id == org,
                WebhookAttemptRow.delivery_id == intent.id,
            )
        )
        is None
    )
    audit = api.session.get(AuditRow, intent.audit_id)
    assert audit and audit.type == "integration.webhook.intent.created"
    assert audit.payload["target_id"] == str(endpoint_id)
    assert "secret_reference" not in str(audit.payload)

    with pytest.raises(ServiceError) as unavailable:
        process_webhook(org, intent.id)
    assert unavailable.value.code == "webhook_signing_secret_unavailable"
    initial_state = api.session.get(WebhookDeliveryStateRow, (intent.id, org))
    assert initial_state is not None and initial_state.status == "pending"

    delivery = WebhookDeliveryService(
        WebhookDeliveryRepository(api.session),
        WebhookEndpointRepository(api.session),
        AutomationRepository(api.session),
        AuditRepository(api.session),
        UnconfiguredTenantSecretResolver(),
        cast(WebhookTransport, object()),
    )
    claimed = delivery.claim(org, intent.id)
    assert claimed and claimed.status == "sending" and claimed.attempts == 1
    assert delivery.claim(org, intent.id) is None
    expired_at = claimed.next_at + timedelta(seconds=1)
    due = WebhookDeliveryRepository(api.session).due(expired_at)
    assert any(row.id == intent.id and row.status == "sending" for row in due)
    assert delivery.claim(org, intent.id, now=expired_at) is None
    api.session.flush()
    api.session.refresh(state)
    assert state.status == "uncertain" and state.attempts == 1
    base = f"/api/v1/organizations/{org}/webhook-deliveries"
    listed = api.client.get(
        base,
        headers=api.headers("admin"),
        params={"workspace_id": str(workspace)},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 1
    assert "url" not in listed.text and "secret_reference" not in listed.text
    history = api.client.get(f"{base}/{intent.id}", headers=api.headers("admin"))
    assert history.status_code == 200, history.text
    assert history.json()["delivery"]["state"] == "uncertain"
    assert history.json()["attempts"][0]["outcome"] == "uncertain"
    token = api.invitation(org, workspace, role="Viewer", email="webhook-viewer@example.com")
    api.accept(org, token, subject="webhook-viewer", email="webhook-viewer@example.com")
    denied = api.client.get(f"{base}/{intent.id}", headers=api.headers("webhook-viewer"))
    assert denied.status_code == 403
    preview = api.client.post(
        f"{base}/{intent.id}/replay", headers=api.headers("admin"), json={"dry_run": True}
    )
    assert preview.status_code == 200, preview.text
    digest = preview.json()["review_sha256"]
    refused = api.client.post(
        f"{base}/{intent.id}/replay",
        headers=api.headers("admin"),
        json={"dry_run": False, "review_sha256": digest, "reason": "Reviewed fake failure"},
    )
    assert refused.status_code == 422
    applied = api.client.post(
        f"{base}/{intent.id}/replay",
        headers=api.headers("admin"),
        json={
            "dry_run": False,
            "review_sha256": digest,
            "reason": "Reviewed fake failure",
            "acknowledge_uncertain": True,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["delivery"]["state"] == "retry"
    assert len(api.session.scalars(select(WebhookAttemptRow)).all()) == 1
