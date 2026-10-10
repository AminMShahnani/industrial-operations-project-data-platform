from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid7

import pytest
from operations.composition import compose
from operations.modules.audit.infrastructure.persistence import AuditRepository, AuditRow
from operations.modules.automation.application.contracts import RuleDefinition, WebhookAction
from operations.modules.automation.application.events import DeliveryMessage, OperationalEvent
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import AutomationRepository
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
    endpoint = api.client.post(
        f"/api/v1/organizations/{org}/webhook-endpoints",
        headers=api.headers("admin"),
        params={"workspace_id": str(workspace), "project_id": str(project_id)},
        json={
            "name": "Delivery integration test",
            "url": "https://hooks.example.test/events",
            "secret_reference": "tenant/webhooks/integration-test/key-v1",
            "signing_key_version": 1,
        },
    )
    assert endpoint.status_code == 201, endpoint.text
    endpoint_id = UUID(endpoint.json()["endpoint_id"])
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
    api.session.flush()
    api.session.refresh(state)
    assert state.status == "sending" and state.attempts == 1
