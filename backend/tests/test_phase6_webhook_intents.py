from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid5, uuid7

import pytest
from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditEvent
from operations.modules.automation.application.contracts import Rule, Run, WebhookAction
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.integrations.application.automation import WebhookAutomationActions
from operations.modules.integrations.application.contracts import EndpointVersion
from operations.modules.integrations.application.delivery_contracts import WebhookIntent


class FormsStub:
    def __init__(self, user_id: UUID) -> None:
        self.authorization = SimpleNamespace(user=lambda *_args: SimpleNamespace(id=user_id))
        self.checks: list[tuple[object, ...]] = []

    def require(self, *args: object) -> None:
        self.checks.append(args)


class EndpointStub:
    def __init__(self, pinned: EndpointVersion, latest: EndpointVersion) -> None:
        self.pinned, self.head = pinned, latest

    def version(
        self, organization_id: UUID, endpoint_id: UUID, version: int
    ) -> EndpointVersion | None:
        if (organization_id, endpoint_id, version) == (
            self.pinned.organization_id,
            self.pinned.endpoint_id,
            self.pinned.version,
        ):
            return self.pinned
        return None

    def latest(self, organization_id: UUID, endpoint_id: UUID) -> EndpointVersion | None:
        if (organization_id, endpoint_id) == (self.head.organization_id, self.head.endpoint_id):
            return self.head
        return None

    def add(self, _row: EndpointVersion) -> None:
        raise AssertionError("endpoint store is read-only in this test")

    def page(self, *_args: object) -> list[EndpointVersion]:
        raise AssertionError("endpoint paging is not used in this test")


class IntentStub:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], WebhookIntent] = {}

    def get(self, organization_id: UUID, identifier: UUID) -> WebhookIntent | None:
        return self.rows.get((organization_id, identifier))

    def add(self, row: WebhookIntent) -> None:
        self.rows[(row.organization_id, row.id)] = row


class AuditStub:
    def __init__(self) -> None:
        self.rows: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.rows.append(event)


@pytest.fixture
def intent_setup() -> tuple[
    WebhookAutomationActions, Rule, OperationalEvent, Run, RequestContext, AuditStub
]:
    organization, workspace, project, endpoint_id, user_id = (
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
    )
    rule_version_id, run_id, event_id = uuid7(), uuid7(), uuid7()
    now = datetime.now(UTC)
    endpoint = EndpointVersion(
        audit_id=uuid7(),
        endpoint_id=endpoint_id,
        organization_id=organization,
        workspace_id=workspace,
        project_id=project,
        version=2,
        signing_key_version=3,
        name="Receiver",
        url="https://hooks.example.test/events",
        secret_reference="tenant/integrations/key-v3",
        created_by_id=user_id,
        created_at=now,
    )
    rule = Rule(
        id=uuid7(),
        organization_id=organization,
        workspace_id=workspace,
        project_id=project,
        name="Approved submission hook",
    )
    event = OperationalEvent(
        id=event_id,
        type="submission.approved",
        occurred_at=now,
        organization_id=organization,
        workspace_id=workspace,
        project_id=project,
        actor_id=user_id,
        correlation_id=uuid7(),
        aggregate_type="submission",
        aggregate_id=uuid7(),
    )
    run = Run(
        id=run_id,
        organization_id=organization,
        workspace_id=workspace,
        rule_version_id=rule_version_id,
        event_id=event_id,
        delegator_id=user_id,
        trigger_actor_id=user_id,
        correlation_id=event.correlation_id,
        next_at=now,
        created_at=now,
    )
    audit_writer = AuditStub()
    audit_bus = AuditedEventBus(audit_writer)
    forms = FormsStub(user_id)
    service = WebhookAutomationActions(
        cast(FormService, forms),
        EndpointStub(endpoint, endpoint),
        IntentStub(),
        audit_bus,
    )
    actor = RequestContext(Principal("test-issuer", "operator"), run.id, event.correlation_id)
    return service, rule, event, run, actor, audit_writer


def test_automation_records_durable_ids_only_intent_and_bound_audit(
    intent_setup: tuple[
        WebhookAutomationActions, Rule, OperationalEvent, Run, RequestContext, AuditStub
    ],
) -> None:
    service, rule, event, run, actor, audits = intent_setup
    action = WebhookAction(kind="call_webhook", endpoint_id=uuid7(), endpoint_version=2)
    endpoint_store = cast(EndpointStub, service.endpoints)
    endpoint_store.pinned = endpoint_store.pinned.model_copy(
        update={"endpoint_id": action.endpoint_id}
    )
    endpoint_store.head = endpoint_store.pinned
    with cast(AuditedEventBus, service.audit).delegated(run.rule_version_id, event, run):
        identifier = service.execute(actor, rule, event, run, 4, action)
        replayed = service.execute(actor, rule, event, run, 4, action)

    intent = service.intents.get(rule.organization_id, identifier)
    assert intent is not None and identifier == replayed
    assert intent.id == uuid5(run.id, "webhook-delivery:4")
    assert (intent.event_id, intent.run_id, intent.endpoint_id, intent.endpoint_version) == (
        event.id,
        run.id,
        action.endpoint_id,
        2,
    )
    assert "url" not in WebhookIntent.model_fields
    assert "secret_reference" not in WebhookIntent.model_fields
    assert len(audits.rows) == 1
    audit = audits.rows[0]
    assert audit.type == "integration.webhook.intent.created"
    assert audit.payload.authorization_kind == "delegated_automation"
    assert audit.payload.run_id == run.id
    assert audit.payload.rule_version_id == run.rule_version_id
    assert action.endpoint_id == audit.payload.target_id


def test_intent_rejects_endpoint_scope_mismatch_and_latest_revocation_before_write(
    intent_setup: tuple[
        WebhookAutomationActions, Rule, OperationalEvent, Run, RequestContext, AuditStub
    ],
) -> None:
    service, rule, event, run, actor, audits = intent_setup
    endpoint_store = cast(EndpointStub, service.endpoints)
    action = WebhookAction(
        kind="call_webhook", endpoint_id=endpoint_store.pinned.endpoint_id, endpoint_version=2
    )
    endpoint_store.pinned = endpoint_store.pinned.model_copy(update={"workspace_id": uuid7()})
    endpoint_store.head = endpoint_store.pinned
    with pytest.raises(ServiceError, match="webhook_endpoint_scope_or_version_mismatch"):
        service.execute(actor, rule, event, run, 0, action)
    endpoint_store.pinned = endpoint_store.pinned.model_copy(
        update={"workspace_id": rule.workspace_id}
    )
    endpoint_store.head = endpoint_store.pinned.model_copy(
        update={"version": 3, "state": "revoked"}
    )
    with pytest.raises(ServiceError, match="webhook_endpoint_revoked"):
        service.execute(actor, rule, event, run, 0, action)
    assert audits.rows == []
    assert service.intents.get(rule.organization_id, uuid5(run.id, "webhook-delivery:0")) is None
