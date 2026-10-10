"""Bounded webhook attempt lifecycle; external I/O is outside database transactions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.integrations.application.contracts import EndpointStore, EndpointVersion
from operations.modules.integrations.application.delivery_contracts import (
    WebhookAttempt,
    WebhookDeliveryState,
    WebhookDeliveryStore,
    WebhookIntent,
    WebhookSourceReader,
)
from operations.modules.integrations.application.webhooks import (
    TenantSecretResolver,
    WebhookTransport,
    deliver_webhook,
)

WebhookOutcome = Literal["sent", "retry", "failed", "uncertain", "skipped"]


@dataclass(frozen=True)
class WebhookDeliverySnapshot:
    intent: WebhookIntent
    event: OperationalEvent | None
    endpoint: EndpointVersion | None
    head: EndpointVersion | None


class WebhookDeliveryService:
    def __init__(
        self,
        store: WebhookDeliveryStore,
        endpoints: EndpointStore,
        events: WebhookSourceReader,
        audit: AuditWriter,
        secrets: TenantSecretResolver,
        transport: WebhookTransport,
        allowed_private_cidrs: tuple[str, ...] = (),
    ) -> None:
        self.store, self.endpoints, self.events = store, endpoints, events
        self.audit, self.secrets, self.transport = audit, secrets, transport
        self.allowed_private_cidrs = allowed_private_cidrs

    def _audit(
        self,
        intent: WebhookIntent,
        at: datetime,
        kind: str,
        outcome: str,
        attempts: int,
        reason: str | None = None,
    ) -> UUID:
        identifier = uuid7()
        self.audit.append(
            AuditEvent(
                id=identifier,
                type=kind,
                occurred_at=at,
                organization_id=intent.organization_id,
                actor_id=None,
                correlation_id=intent.correlation_id,
                request_id=intent.id,
                aggregate_type="webhook_delivery",
                aggregate_id=intent.id,
                payload=AuditDetails(
                    workspace_id=intent.workspace_id,
                    project_id=intent.project_id,
                    outcome=outcome,
                    version=attempts,
                    reason=reason,
                ),
            )
        )
        return identifier

    def claim(self, org: UUID, identifier: UUID) -> WebhookDeliveryState | None:
        state = self.store.state(org, identifier, lock=True)
        intent = self.store.intent(org, identifier)
        if state is None or intent is None:
            raise ServiceError(404, "webhook_delivery_not_found")
        now = datetime.now(UTC)
        if state.status in {"sent", "failed", "uncertain", "skipped"} or state.next_at > now:
            return None
        event = self.events.event(org, intent.event_id)
        if event is None:
            raise ServiceError(409, "webhook_delivery_source_missing")
        if state.status == "sending":
            # A worker vanished after the lease was committed; outcome may be uncertain.
            self._finish(intent, state, "uncertain", "webhook_claim_expired", state.updated_at)
            return None
        if state.attempts >= 8:
            self._finish(intent, state, "failed", "webhook_attempt_limit", state.updated_at)
            return None
        updated = state.model_copy(
            update={
                "status": "sending",
                "attempts": state.attempts + 1,
                "next_at": now + timedelta(seconds=90),
                "updated_at": now,
                "error_code": None,
                "audit_id": self._audit(
                    intent,
                    now,
                    "integration.webhook.delivery.updated",
                    "sending",
                    state.attempts + 1,
                ),
            }
        )
        self.store.save_state(updated)
        return updated

    def prepare(self, org: UUID, identifier: UUID) -> WebhookDeliverySnapshot:
        intent = self.store.intent(org, identifier)
        if intent is None:
            raise ServiceError(404, "webhook_delivery_not_found")
        event = self.events.event(org, intent.event_id)
        endpoint = self.endpoints.version(org, intent.endpoint_id, intent.endpoint_version)
        head = self.endpoints.latest(org, intent.endpoint_id)
        return WebhookDeliverySnapshot(intent, event, endpoint, head)

    def transmit(
        self, snapshot: WebhookDeliverySnapshot, attempt: int
    ) -> tuple[WebhookOutcome, str | None]:
        if snapshot.event is None or snapshot.endpoint is None or snapshot.head is None:
            return "failed", "webhook_delivery_integrity"
        try:
            deliver_webhook(
                snapshot.event,
                snapshot.intent.id,
                snapshot.endpoint,
                snapshot.head,
                self.secrets,
                self.transport,
                self.allowed_private_cidrs,
            )
            return "sent", None
        except ServiceError as error:
            outcome: WebhookOutcome = (
                "uncertain"
                if error.code == "webhook_delivery_uncertain"
                else "retry"
                if error.status == 503 and attempt < 8
                else "skipped"
                if error.code == "webhook_endpoint_revoked"
                else "failed"
            )
            return outcome, error.code

    def finish(
        self,
        org: UUID,
        identifier: UUID,
        claimed: WebhookDeliveryState,
        result: WebhookOutcome,
        code: str | None,
    ) -> WebhookDeliveryState:
        intent = self.store.intent(org, identifier)
        state = self.store.state(org, identifier, lock=True)
        if (
            intent is None
            or state is None
            or state.status != "sending"
            or state.attempts != claimed.attempts
        ):
            raise ServiceError(409, "webhook_delivery_claim_conflict")
        return self._finish(intent, state, result, code, claimed.updated_at)

    def _finish(
        self,
        intent: WebhookIntent,
        state: WebhookDeliveryState,
        result: WebhookOutcome,
        code: str | None,
        started_at: datetime,
    ) -> WebhookDeliveryState:
        now = datetime.now(UTC)
        delay = min(5 * 2 ** max(0, state.attempts - 1), 3600)
        next_at = now + timedelta(seconds=delay) if result == "retry" else now
        state_audit = self._audit(
            intent, now, "integration.webhook.delivery.updated", result, state.attempts, code
        )
        changed = state.model_copy(
            update={
                "status": result,
                "next_at": next_at,
                "updated_at": now,
                "error_code": code,
                "audit_id": state_audit,
            }
        )
        self.store.save_state(changed)
        attempt_audit = self._audit(
            intent, now, "integration.webhook.attempted", result, state.attempts, code
        )
        self.store.add_attempt(
            WebhookAttempt(
                id=uuid7(),
                organization_id=intent.organization_id,
                delivery_id=intent.id,
                number=state.attempts,
                outcome=result,
                error_code=code,
                started_at=started_at,
                finished_at=now,
                audit_id=attempt_audit,
            )
        )
        return changed
