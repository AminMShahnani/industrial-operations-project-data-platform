"""Bounded webhook attempt lifecycle; external I/O is outside database transactions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.forms.application.service import FormService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.integrations.application.contracts import EndpointStore, EndpointVersion
from operations.modules.integrations.application.delivery_contracts import (
    WebhookAttempt,
    WebhookAttemptView,
    WebhookDeliveryAdminStore,
    WebhookDeliveryAuthorityReader,
    WebhookDeliveryHistory,
    WebhookDeliveryPage,
    WebhookDeliveryReview,
    WebhookDeliveryState,
    WebhookDeliveryStatus,
    WebhookDeliveryStore,
    WebhookDeliveryView,
    WebhookIntent,
    WebhookSourceReader,
)
from operations.modules.integrations.application.service import WebhookEndpointService
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

    def claim(
        self, org: UUID, identifier: UUID, now: datetime | None = None
    ) -> WebhookDeliveryState | None:
        state = self.store.state(org, identifier, lock=True)
        intent = self.store.intent(org, identifier)
        if state is None or intent is None:
            raise ServiceError(404, "webhook_delivery_not_found")
        now = now or datetime.now(UTC)
        if state.status in {"sent", "failed", "uncertain", "skipped"}:
            return None
        if state.status == "sending":
            if state.next_at > now:
                return None
            # A worker vanished after the lease was committed; outcome may be uncertain.
            self._finish(intent, state, "uncertain", "webhook_claim_expired", state.updated_at)
            return None
        if state.next_at > now:
            return None
        event = self.events.event(org, intent.event_id)
        if event is None:
            raise ServiceError(409, "webhook_delivery_source_missing")
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


class WebhookDeliveryAdminService:
    """Scoped operator inspection and reasoned replay of retained webhook evidence."""

    def __init__(
        self,
        store: WebhookDeliveryAdminStore,
        sources: WebhookDeliveryAuthorityReader,
        forms: FormService,
        endpoint_authority: WebhookEndpointService,
        audit: AuditWriter,
    ) -> None:
        self.store, self.sources = store, sources
        self.forms, self.endpoint_authority, self.audit = forms, endpoint_authority, audit

    @staticmethod
    def _view(intent: WebhookIntent, state: WebhookDeliveryState) -> WebhookDeliveryView:
        return WebhookDeliveryView(
            id=intent.id,
            organization_id=intent.organization_id,
            workspace_id=intent.workspace_id,
            project_id=intent.project_id,
            endpoint_id=intent.endpoint_id,
            endpoint_version=intent.endpoint_version,
            state=state.status,
            attempts=state.attempts,
            next_at=state.next_at,
            error_code=state.error_code,
            created_at=intent.created_at,
        )

    def _intent(self, org: UUID, identifier: UUID) -> WebhookIntent:
        intent = self.store.intent(org, identifier)
        if intent is None:
            raise ServiceError(404, "webhook_delivery_not_found")
        return intent

    def _operator(self, actor: RequestContext, intent: WebhookIntent) -> UUID:
        # Keep this dependency at the owning endpoint service boundary.
        return self.endpoint_authority.require(
            actor, intent.organization_id, intent.workspace_id, intent.project_id
        )

    def _delegation(self, intent: WebhookIntent) -> RequestContext:
        run = self.sources.run(intent.organization_id, intent.run_id)
        version = self.sources.version_by_id(intent.organization_id, intent.rule_version_id)
        if (
            run is None
            or version is None
            or run.rule_version_id != version.id
            or run.event_id != intent.event_id
            or run.organization_id != intent.organization_id
            or run.workspace_id != intent.workspace_id
            or run.delegator_id != intent.requested_by_id
            or run.delegator_id != version.activator_id
        ):
            raise ServiceError(403, "automation_delegation_revoked")
        user = self.forms.authorization.identities.by_id(intent.organization_id, run.delegator_id)
        if user is None or not user.active:
            raise ServiceError(403, "automation_delegation_revoked")
        delegated = RequestContext(Principal(user.issuer, user.subject), run.id, run.correlation_id)
        self.forms.authorization.require(
            delegated,
            "organization.manage",
            Scope(intent.organization_id, ScopeType.ORGANIZATION, intent.organization_id),
        )
        self.forms.require(
            delegated,
            intent.organization_id,
            intent.workspace_id,
            intent.project_id,
            "automation.manage",
            True,
        )
        self.forms.require(
            delegated,
            intent.organization_id,
            intent.workspace_id,
            intent.project_id,
            "integration.manage",
            True,
        )
        return delegated

    def page(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID | None = None,
        project: UUID | None = None,
        state: WebhookDeliveryStatus | None = None,
        cursor: UUID | None = None,
    ) -> WebhookDeliveryPage:
        if project is not None and workspace is None:
            raise ServiceError(422, "webhook_delivery_workspace_required")
        if workspace is None:
            self.forms.authorization.require(
                actor,
                "integration.manage",
                Scope(org, ScopeType.ORGANIZATION, org),
            )
        else:
            self.endpoint_authority.require(actor, org, workspace, project)
        rows = self.store.page(org, workspace, project, state, cursor, 101)
        views = [self._view(intent, delivery) for intent, delivery in rows]
        return WebhookDeliveryPage(
            items=views[:100], next_cursor=views[99].id if len(views) > 100 else None
        )

    def history(self, actor: RequestContext, org: UUID, identifier: UUID) -> WebhookDeliveryHistory:
        intent = self._intent(org, identifier)
        self._operator(actor, intent)
        state = self.store.state(org, identifier)
        if state is None:
            raise ServiceError(409, "webhook_delivery_integrity")
        attempts = self.store.attempts(org, identifier)
        return WebhookDeliveryHistory(
            delivery=self._view(intent, state),
            attempts=[
                WebhookAttemptView(
                    number=item.number,
                    outcome=item.outcome,
                    error_code=item.error_code,
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                )
                for item in attempts
            ],
        )

    def replay(
        self,
        actor: RequestContext,
        org: UUID,
        identifier: UUID,
        *,
        apply: bool = False,
        review_sha256: str | None = None,
        reason: str | None = None,
        acknowledge_uncertain: bool = False,
    ) -> WebhookDeliveryReview:
        intent = self._intent(org, identifier)
        operator_id = self._operator(actor, intent)
        self._delegation(intent)
        state = self.store.state(org, identifier, lock=apply)
        if state is None:
            raise ServiceError(409, "webhook_delivery_integrity")
        attempts = self.store.attempts(org, identifier)
        if state.status not in {"retry", "failed", "uncertain"} or state.attempts >= 20:
            raise ServiceError(409, "webhook_delivery_not_replayable")
        view = self._view(intent, state)
        evidence = {
            "delivery": view.model_dump(mode="json"),
            "attempts": [item.model_dump(mode="json") for item in attempts],
        }
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if not apply:
            return WebhookDeliveryReview(delivery=view, review_sha256=digest)
        if state.status == "uncertain" and not acknowledge_uncertain:
            raise ServiceError(422, "webhook_uncertain_acknowledgement_required")
        if review_sha256 != digest:
            raise ServiceError(409, "webhook_review_stale")
        if not reason or not 1 <= len(reason.strip()) <= 500:
            raise ServiceError(422, "webhook_replay_reason_required")
        now = datetime.now(UTC)
        delivery_audit = uuid7()
        changed = state.model_copy(
            update={
                "status": "retry",
                "next_at": now,
                "updated_at": now,
                "error_code": None,
                "audit_id": delivery_audit,
            }
        )
        self.audit.append(
            AuditEvent(
                id=delivery_audit,
                type="integration.webhook.delivery.updated",
                occurred_at=now,
                organization_id=org,
                actor_id=None,
                correlation_id=intent.correlation_id,
                request_id=intent.id,
                aggregate_type="webhook_delivery",
                aggregate_id=intent.id,
                payload=AuditDetails(
                    workspace_id=intent.workspace_id,
                    project_id=intent.project_id,
                    outcome="retry",
                    version=state.attempts,
                ),
            )
        )
        self.store.save_state(changed)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="integration.webhook.delivery.replayed",
                occurred_at=now,
                organization_id=org,
                actor_id=operator_id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="webhook_delivery",
                aggregate_id=intent.id,
                payload=AuditDetails(
                    workspace_id=intent.workspace_id,
                    project_id=intent.project_id,
                    target_id=intent.endpoint_id,
                    outcome="requeued",
                    version=state.attempts,
                    reason=reason.strip(),
                ),
            )
        )
        return WebhookDeliveryReview(
            delivery=self._view(intent, changed), review_sha256=digest, applied=True
        )
