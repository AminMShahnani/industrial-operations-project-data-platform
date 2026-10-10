"""Automation adapter that records durable webhook intent without sending network traffic."""

from datetime import UTC, datetime
from uuid import UUID, uuid5, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.automation.application.contracts import (
    AutomationAction,
    Rule,
    Run,
    WebhookAction,
)
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.integrations.application.contracts import EndpointStore
from operations.modules.integrations.application.delivery_contracts import (
    WebhookIntent,
    WebhookIntentStore,
)


class WebhookAutomationActions:
    """Recheck endpoint authority and atomically record IDs-only action intent."""

    def __init__(
        self,
        forms: FormService,
        endpoints: EndpointStore,
        intents: WebhookIntentStore,
        audit: AuditWriter,
    ) -> None:
        self.forms, self.endpoints, self.intents, self.audit = forms, endpoints, intents, audit

    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None:
        if not isinstance(action, WebhookAction):
            raise ServiceError(422, "automation_action_not_configured")
        self.forms.require(
            actor,
            rule.organization_id,
            rule.workspace_id,
            rule.project_id,
            "integration.manage",
            True,
        )
        pinned = self.endpoints.version(
            rule.organization_id, action.endpoint_id, action.endpoint_version
        )
        latest = self.endpoints.latest(rule.organization_id, action.endpoint_id)
        if pinned is None or latest is None:
            raise ServiceError(422, "webhook_endpoint_version_not_found")
        if pinned.state != "active" or latest.state != "active":
            raise ServiceError(422, "webhook_endpoint_revoked")
        if (
            latest.endpoint_id != pinned.endpoint_id
            or latest.organization_id != pinned.organization_id
            or latest.version < pinned.version
            or (latest.workspace_id, latest.project_id) != (pinned.workspace_id, pinned.project_id)
            or (pinned.organization_id, pinned.workspace_id, pinned.project_id)
            != (rule.organization_id, rule.workspace_id, rule.project_id)
        ):
            raise ServiceError(422, "webhook_endpoint_scope_or_version_mismatch")

    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID:
        if not isinstance(action, WebhookAction):
            raise ServiceError(422, "automation_action_not_configured")
        self.validate(actor, rule, action)
        if (
            (event.organization_id, event.workspace_id, event.project_id)
            != (rule.organization_id, rule.workspace_id, rule.project_id)
            or (run.organization_id, run.workspace_id, run.event_id)
            != (event.organization_id, event.workspace_id, event.id)
            or position < 0
            or position > 19
        ):
            raise ServiceError(409, "webhook_intent_source_scope_mismatch")

        identifier = uuid5(run.id, f"webhook-delivery:{position}")
        existing = self.intents.get(rule.organization_id, identifier)
        if existing is not None:
            if (
                existing.run_id != run.id
                or existing.event_id != event.id
                or existing.endpoint_id != action.endpoint_id
                or existing.endpoint_version != action.endpoint_version
                or existing.action_position != position
                or existing.rule_version_id != run.rule_version_id
            ):
                raise ServiceError(409, "webhook_intent_identity_conflict")
            return existing.id

        now = datetime.now(UTC)
        requested_by = self.forms.authorization.user(actor, rule.organization_id).id
        row = WebhookIntent(
            id=identifier,
            audit_id=uuid7(),
            organization_id=rule.organization_id,
            workspace_id=rule.workspace_id,
            project_id=rule.project_id,
            event_id=event.id,
            run_id=run.id,
            rule_version_id=run.rule_version_id,
            action_position=position,
            endpoint_id=action.endpoint_id,
            endpoint_version=action.endpoint_version,
            requested_by_id=requested_by,
            correlation_id=event.correlation_id,
            created_at=now,
        )
        self.audit.append(
            AuditEvent(
                id=row.audit_id,
                type="integration.webhook.intent.created",
                occurred_at=now,
                organization_id=rule.organization_id,
                actor_id=requested_by,
                correlation_id=event.correlation_id,
                request_id=run.id,
                aggregate_type="webhook_delivery",
                aggregate_id=row.id,
                payload=AuditDetails(
                    target_id=action.endpoint_id,
                    workspace_id=rule.workspace_id,
                    project_id=rule.project_id,
                    version=action.endpoint_version,
                    scope_type="workspace",
                    scope_id=rule.workspace_id,
                    run_id=run.id,
                    rule_version_id=run.rule_version_id,
                    outcome="intent_created",
                ),
            )
        )
        self.intents.add(row)
        return row.id
