import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent, AuditWriter
from operations.modules.automation.application.contracts import (
    AutomationAction,
    AutomationStore,
    NotifyAction,
    Receipt,
    Rule,
    RuleDefinition,
    RuleVersion,
    Run,
    RunAttempt,
)
from operations.modules.automation.application.event_bus import AuditedEventBus
from operations.modules.automation.application.events import (
    Delivery,
    DeliveryMessage,
    EventContext,
    JobPublisher,
    NotificationHandoff,
    NotificationReplayReview,
    OperationalEvent,
)
from operations.modules.automation.domain.reliability import (
    delivery_id,
    next_causation,
    retry_delay,
)
from operations.modules.forms.application.contracts import FormValues
from operations.modules.forms.application.expressions import condition_matches, validate_condition
from operations.modules.forms.application.runtime import components
from operations.modules.forms.application.service import FormService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext


class ActionExecutor(Protocol):
    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None: ...
    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None: ...
    def values(self, actor: RequestContext, event: OperationalEvent) -> FormValues: ...


def definition_hash(definition: RuleDefinition) -> str:
    return hashlib.sha256(
        json.dumps(
            definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class AutomationService:
    def __init__(
        self,
        store: AutomationStore,
        forms: FormService,
        audit: AuditedEventBus,
        actions: ActionExecutor,
    ) -> None:
        self.store, self.forms, self.audit, self.actions = store, forms, audit, actions

    def require(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        manage: bool = False,
    ) -> None:
        self.forms.require(
            actor,
            org,
            workspace,
            project,
            "automation.manage" if manage else "automation.read",
            manage,
        )

    def audit_event(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        action: str,
        reason: str | None = None,
        version: int | None = None,
    ) -> None:
        user = self.forms.authorization.user(actor, org)
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=org,
                actor_id=user.id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="automation",
                aggregate_id=identifier,
                payload=AuditDetails(
                    scope_type="workspace", scope_id=workspace, reason=reason, version=version
                ),
            )
        )

    def get(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        manage: bool = False,
    ) -> Rule:
        row = self.store.rule(org, workspace, identifier)
        if row is None:
            raise ServiceError(404, "not_found")
        self.require(actor, org, workspace, row.project_id, manage)
        if manage:
            locked = self.store.rule(org, workspace, identifier, True)
            if locked is None:
                raise ServiceError(404, "not_found")
            row = locked
        return row

    def check(self, actor: RequestContext, rule: Rule, definition: RuleDefinition) -> None:
        keys = {"event_type", "project_phase", "form_number", "subject_user_id"}
        if definition.form_id and definition.form_number:
            form, version = self.forms.version(
                actor,
                rule.organization_id,
                rule.workspace_id,
                definition.form_id,
                definition.form_number,
            )
            if form.project_id != rule.project_id or version.state != "published":
                raise ServiceError(422, "automation_form_scope_or_state")
            keys.update(
                "form_" + field.key
                for field in components(version.definition)
                if field.kind
                not in {"table", "repeating_group", "multi_select", "file", "image", "signature"}
                and len(field.key) <= 55
            )
        if definition.condition:
            validate_condition(definition.condition, keys)
        for action in definition.actions:
            if isinstance(action, NotifyAction) and definition.trigger in {
                "scheduled.timer",
                "integration.event",
                "master_data.changed",
            }:
                raise ServiceError(422, "notification_source_not_configured")
            self.actions.validate(actor, rule, action)

    def create(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        name: str,
        definition: RuleDefinition,
    ) -> Rule:
        self.require(actor, org, workspace, project, True)
        row = Rule(
            id=uuid7(), organization_id=org, workspace_id=workspace, project_id=project, name=name
        )
        self.check(actor, row, definition)
        self.store.create_rule(row)
        self.store.add_version(
            RuleVersion(
                id=uuid7(),
                organization_id=org,
                workspace_id=workspace,
                rule_id=row.id,
                number=1,
                definition=definition,
            )
        )
        self.audit_event(actor, org, workspace, row.id, "automation.rule.created", version=1)
        return row

    def version(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        manage: bool = False,
    ) -> tuple[Rule, RuleVersion]:
        row = self.get(actor, org, workspace, identifier, manage)
        version = self.store.version(org, workspace, identifier, number, manage)
        if version is None:
            raise ServiceError(404, "not_found")
        if version.state == "draft":
            self.require(actor, org, workspace, row.project_id, True)
        return row, version

    def save(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        definition: RuleDefinition,
    ) -> RuleVersion:
        row, version = self.version(actor, org, workspace, identifier, number, True)
        if version.state != "draft":
            raise ServiceError(409, "immutable_automation_version")
        self.check(actor, row, definition)
        changed = version.model_copy(update={"definition": definition, "revision": expected + 1})
        if version.revision != expected or not self.store.save_version(changed, expected):
            raise ServiceError(409, "version_conflict")
        self.audit_event(
            actor, org, workspace, version.id, "automation.version.saved", version=number
        )
        return changed

    def clone(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        source: int,
        number: int,
    ) -> RuleVersion:
        _, version = self.version(actor, org, workspace, identifier, source, True)
        if self.store.version(org, workspace, identifier, number):
            raise ServiceError(409, "version_exists")
        row = RuleVersion(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            rule_id=identifier,
            number=number,
            definition=version.definition,
        )
        self.store.add_version(row)
        self.audit_event(
            actor, org, workspace, row.id, "automation.version.created", version=number
        )
        return row

    def activate(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        dry_run: bool,
        content_sha256: str | None,
    ) -> RuleVersion:
        user = self.forms.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        )
        row, version = self.version(actor, org, workspace, identifier, number, True)
        if version.state != "draft" or version.revision != expected:
            raise ServiceError(409, "version_conflict")
        self.check(actor, row, version.definition)
        digest = definition_hash(version.definition)
        if dry_run:
            return version.model_copy(update={"content_sha256": digest})
        if digest != content_sha256:
            raise ServiceError(409, "automation_activation_review_required")
        if row.active_number is not None:
            old = self.store.version(org, workspace, identifier, row.active_number, True)
            if old is None:
                raise ServiceError(409, "automation_binding_invalid")
            if not self.store.save_version(
                old.model_copy(update={"state": "retired", "revision": old.revision + 1}),
                old.revision,
            ):
                raise ServiceError(409, "version_conflict")
            self.audit_event(
                actor, org, workspace, old.id, "automation.version.retired", version=old.number
            )
        activated = version.model_copy(
            update={
                "state": "active",
                "revision": expected + 1,
                "activator_id": user.id,
                "activated_at": datetime.now(UTC),
                "content_sha256": digest,
            }
        )
        if not self.store.save_version(activated, expected) or not self.store.save_rule(
            row.model_copy(update={"active_number": number, "revision": row.revision + 1}),
            row.revision,
        ):
            raise ServiceError(409, "version_conflict")
        self.audit_event(
            actor, org, workspace, version.id, "automation.version.activated", version=number
        )
        return activated

    def retire(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
        reason: str,
    ) -> Rule:
        row = self.get(actor, org, workspace, identifier, True)
        if row.revision != expected:
            raise ServiceError(409, "version_conflict")
        if row.active_number is not None:
            old = self.store.version(org, workspace, identifier, row.active_number, True)
            if old is None or not self.store.save_version(
                old.model_copy(update={"state": "retired", "revision": old.revision + 1}),
                old.revision,
            ):
                raise ServiceError(409, "version_conflict")
        changed = row.model_copy(update={"active_number": None, "revision": expected + 1})
        if not self.store.save_rule(changed, expected):
            raise ServiceError(409, "version_conflict")
        self.audit_event(actor, org, workspace, identifier, "automation.rule.retired", reason)
        return changed

    def capture(self, event: OperationalEvent) -> None:
        EventCapture(self.store, self.audit).capture(event)

    def delegated_context(self, run: Run) -> RequestContext:
        user = self.forms.authorization.identities.by_id(run.organization_id, run.delegator_id)
        if user is None or not user.active:
            raise ServiceError(403, "automation_delegation_revoked")
        actor = RequestContext(Principal(user.issuer, user.subject), run.id, run.correlation_id)
        self.forms.authorization.require(
            actor,
            "organization.manage",
            Scope(run.organization_id, ScopeType.ORGANIZATION, run.organization_id),
        )
        return actor

    def execute(self, org: UUID, identifier: UUID) -> Run:
        self.lock_tenant(org)
        run = self.store.run(org, identifier, True)
        if run is None:
            raise ServiceError(404, "not_found")
        if run.state in {"completed", "skipped"}:
            return run
        if run.state == "dead_letter" or run.next_at > datetime.now(UTC):
            return run
        version = self.store.version_by_id(org, run.rule_version_id)
        event = self.store.event(org, run.event_id)
        if version is None or event is None or version.activator_id != run.delegator_id:
            raise ServiceError(409, "automation_run_integrity")
        rule = self.store.rule(org, run.workspace_id, version.rule_id)
        if rule is None:
            raise ServiceError(409, "automation_run_integrity")
        with self.audit.delegated(version.id, event, run):
            return self.perform(run, version, event, rule)

    def perform(self, run: Run, version: RuleVersion, event: OperationalEvent, rule: Rule) -> Run:
        org = run.organization_id
        actor = self.delegated_context(run)
        self.require(actor, org, run.workspace_id, rule.project_id, True)
        next_causation(tuple(event.causation_path), version.id)
        started = datetime.now(UTC)
        values = self.actions.values(actor, event)
        if version.definition.condition and not condition_matches(
            version.definition.condition, values
        ):
            outcome: Literal["completed", "skipped"] = "skipped"
        else:
            receipts = {receipt.position for receipt in self.store.receipts(org, run.id)}
            for position, action in enumerate(version.definition.actions):
                if position in receipts:
                    continue
                self.actions.validate(actor, rule, action)
                target = self.actions.execute(actor, rule, event, run, position, action)
                self.store.add_receipt(
                    Receipt(
                        id=uuid7(),
                        organization_id=org,
                        run_id=run.id,
                        position=position,
                        kind=action.kind,
                        target_id=target,
                        created_at=datetime.now(UTC),
                    )
                )
                self.audit_event(
                    actor,
                    org,
                    run.workspace_id,
                    run.id,
                    "automation.action.completed",
                    version=position,
                )
            outcome = "completed"
        finished = datetime.now(UTC)
        changed = run.model_copy(
            update={
                "state": outcome,
                "attempts": run.attempts + 1,
                "completed_at": finished,
                "error_code": None,
            }
        )
        self.store.save_run(changed)
        self.store.add_attempt(
            RunAttempt(
                id=uuid7(),
                organization_id=org,
                run_id=run.id,
                number=changed.attempts,
                started_at=started,
                finished_at=finished,
                outcome=outcome,
            )
        )
        self.audit_event(actor, org, run.workspace_id, run.id, "automation.run." + outcome)
        return changed

    def failed(self, org: UUID, identifier: UUID, code: str, transient: bool) -> Run:
        run = self.store.run(org, identifier, True)
        if run is None:
            raise ServiceError(404, "not_found")
        if run.state in {"completed", "skipped", "dead_letter"}:
            return run
        attempt = run.attempts + 1
        delay = retry_delay(attempt) if attempt <= 8 and transient else None
        now = datetime.now(UTC)
        state: Literal["retry", "dead_letter"] = "retry" if delay is not None else "dead_letter"
        changed = run.model_copy(
            update={
                "state": state,
                "attempts": attempt,
                "next_at": now + timedelta(seconds=delay or 0),
                "error_code": code,
            }
        )
        self.store.save_run(changed)
        self.store.add_attempt(
            RunAttempt(
                id=uuid7(),
                organization_id=org,
                run_id=run.id,
                number=attempt,
                started_at=now,
                finished_at=now,
                outcome=state,
                error_code=code,
            )
        )
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="automation.run." + state,
                occurred_at=now,
                organization_id=org,
                actor_id=None,
                correlation_id=run.correlation_id,
                request_id=run.id,
                aggregate_type="automation",
                aggregate_id=run.id,
                payload=AuditDetails(
                    reason=code,
                    authorized_by=run.delegator_id,
                    scope_type="workspace",
                    scope_id=run.workspace_id,
                ),
            )
        )
        return changed

    def replay(
        self, actor: RequestContext, org: UUID, workspace: UUID, identifier: UUID, reason: str
    ) -> Run:
        run = self.store.run(org, identifier)
        if run is None or run.workspace_id != workspace:
            raise ServiceError(404, "not_found")
        version = self.store.version_by_id(org, run.rule_version_id)
        if version is None:
            raise ServiceError(409, "automation_run_integrity")
        rule = self.get(actor, org, workspace, version.rule_id, True)
        locked = self.store.run(org, identifier, True)
        if locked is None:
            raise ServiceError(404, "not_found")
        run = locked
        self.delegated_context(run)
        if run.state not in {"retry", "dead_letter"}:
            raise ServiceError(409, "automation_run_not_replayable")
        if run.attempts >= 20:
            raise ServiceError(409, "automation_attempt_limit")
        changed = run.model_copy(
            update={"state": "retry", "next_at": datetime.now(UTC), "error_code": None}
        )
        self.store.save_run(changed)
        self.audit_event(
            actor, org, workspace, identifier, "automation.run.replayed", reason, rule.active_number
        )
        delivery = self.store.delivery(org, delivery_id(run.event_id, "automation"), True)
        if delivery:
            self.store.save_delivery(
                delivery.model_copy(
                    update={"state": "retry", "next_at": datetime.now(UTC), "error_code": None}
                )
            )
        return changed

    def dispatch(
        self,
        org: UUID,
        publisher: JobPublisher,
        consumer: Literal["automation", "notifications"] | None = None,
    ) -> int:
        self.lock_tenant(org)
        now = datetime.now(UTC)
        rows = self.store.due_deliveries(org, now, consumer)
        for row in rows:
            publisher.publish(DeliveryMessage(organization_id=org, delivery_id=row.id))
            self.store.save_delivery(
                row.model_copy(
                    update={"state": "dispatched", "next_at": now + timedelta(seconds=60)}
                )
            )
            source = self.store.event(org, row.event_id)
            if source is None:
                raise ServiceError(409, "outbox_delivery_integrity")
            self.audit.append(
                AuditEvent(
                    id=uuid7(),
                    type="outbox.delivery.dispatched",
                    occurred_at=now,
                    organization_id=org,
                    actor_id=None,
                    correlation_id=source.correlation_id,
                    request_id=row.id,
                    aggregate_type="outbox_delivery",
                    aggregate_id=row.id,
                    payload=AuditDetails(
                        workspace_id=source.workspace_id,
                        project_id=source.project_id,
                        reason="durable_dispatch",
                    ),
                )
            )
        return len(rows)

    def replay_notification(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        *,
        dry_run: bool = True,
        review_sha256: str | None = None,
        reason: str | None = None,
    ) -> NotificationReplayReview:
        """Review/requeue one failed delivery without changing its source or audience."""
        self.forms.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        )
        row = self.store.delivery(org, identifier)
        if row is None or row.consumer != "notifications":
            raise ServiceError(404, "notification_delivery_not_found")
        source = self.store.event(org, row.event_id)
        if source is None or source.workspace_id != workspace:
            raise ServiceError(404, "notification_delivery_not_found")
        self.require(actor, org, workspace, source.project_id, True)
        locked = self.store.delivery(org, identifier, True)
        if locked is None:
            raise ServiceError(404, "notification_delivery_not_found")
        row = locked
        if row.state not in {"retry", "dead_letter"}:
            raise ServiceError(409, "notification_delivery_not_replayable")
        if row.attempts >= 20:
            raise ServiceError(409, "notification_attempt_limit")
        digest = hashlib.sha256(
            json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if not dry_run:
            if review_sha256 != digest:
                raise ServiceError(409, "notification_replay_review_required")
            if reason is None or not reason.strip() or len(reason) > 500:
                raise ServiceError(422, "notification_replay_reason_required")
            user = self.forms.authorization.user(actor, org)
            self.audit.append(
                AuditEvent(
                    id=uuid7(),
                    type="outbox.notification.replayed",
                    occurred_at=datetime.now(UTC),
                    organization_id=org,
                    actor_id=user.id,
                    correlation_id=source.correlation_id,
                    request_id=actor.request_id,
                    aggregate_type="outbox_delivery",
                    aggregate_id=row.id,
                    payload=AuditDetails(
                        workspace_id=workspace,
                        project_id=source.project_id,
                        target_id=source.id,
                        version=row.attempts,
                        outcome=row.state,
                        reason=reason.strip(),
                    ),
                )
            )
            row = row.model_copy(
                update={"state": "retry", "next_at": datetime.now(UTC), "error_code": None}
            )
            self.store.save_delivery(row)
        return NotificationReplayReview(
            delivery=row,
            workspace_id=workspace,
            project_id=source.project_id,
            review_sha256=digest,
            applied=not dry_run,
        )

    def notification_handoff_event(self, handoff: NotificationHandoff) -> OperationalEvent | None:
        rows = self.store.handoff_events(handoff)
        if len(rows) > 1:
            raise ServiceError(409, "notification_handoff_source_integrity")
        if not rows:
            return None
        event = rows[0]
        task = handoff.kind == "task_reminder"
        if (
            event.type != ("task.reminder.created" if task else "workflow.notification.requested")
            or event.project_id != handoff.project_id
            or event.payload.recipient_ids != handoff.recipient_ids
            or (event.payload.task_id if task else event.payload.workflow_instance_id)
            != handoff.source_id
            or (task and event.payload.reminder_id != handoff.intent_id)
        ):
            raise ServiceError(409, "notification_handoff_source_integrity")
        if (
            self.store.delivery(handoff.organization_id, delivery_id(event.id, "notifications"))
            is None
        ):
            raise ServiceError(409, "notification_handoff_delivery_integrity")
        return event

    def capture_notification_handoff(
        self, actor: RequestContext, handoff: NotificationHandoff, reason: str
    ) -> UUID:
        org = handoff.organization_id
        user = self.forms.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        )
        self.forms.require(
            actor, org, handoff.workspace_id, handoff.project_id, "automation.manage"
        )
        if not reason.strip() or len(reason) > 500:
            raise ServiceError(422, "notification_handoff_reason_required")
        existing = self.notification_handoff_event(handoff)
        if existing is not None:
            return existing.id
        task = handoff.kind == "task_reminder"
        now = datetime.now(UTC)
        event = OperationalEvent(
            id=handoff.intent_id,
            organization_id=org,
            workspace_id=handoff.workspace_id,
            project_id=handoff.project_id,
            actor_id=user.id,
            correlation_id=actor.correlation_id,
            type="task.reminder.created" if task else "workflow.notification.requested",
            occurred_at=now,
            aggregate_type="task" if task else "workflow",
            aggregate_id=handoff.source_id if task else handoff.intent_id,
            payload=EventContext(
                task_id=handoff.source_id if task else None,
                workflow_instance_id=None if task else handoff.source_id,
                recipient_ids=handoff.recipient_ids,
                scheduled_at=handoff.scheduled_at,
                reminder_id=handoff.intent_id if task else None,
            ),
        )
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="notification.handoff.reconciled",
                occurred_at=now,
                organization_id=org,
                actor_id=user.id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="notification_handoff",
                aggregate_id=handoff.intent_id,
                payload=AuditDetails(
                    workspace_id=handoff.workspace_id,
                    project_id=handoff.project_id,
                    target_id=handoff.source_id,
                    source_created_at=handoff.created_at,
                    reminder_id=handoff.intent_id if task else None,
                    workflow_instance_id=None if task else handoff.source_id,
                    scheduled_at=handoff.scheduled_at,
                    reason=reason,
                ),
            )
        )
        self.store.append(event)
        self.store.add_delivery(
            Delivery(
                id=delivery_id(event.id, "notifications"),
                organization_id=org,
                event_id=event.id,
                consumer="notifications",
                next_at=now,
            )
        )
        return event.id

    def lock_tenant(self, org: UUID) -> None:
        self.forms.workspaces.organizations.lock(org)

    def notification_delivery(self, message: DeliveryMessage) -> tuple[Delivery, OperationalEvent]:
        """Trusted worker handoff; expose immutable source and a locked scoped delivery."""
        self.lock_tenant(message.organization_id)
        delivery = self.store.delivery(message.organization_id, message.delivery_id, True)
        if delivery is None:
            raise ServiceError(404, "outbox_delivery_not_found")
        if delivery.consumer != "notifications":
            raise ServiceError(422, "outbox_consumer_mismatch")
        source = self.store.event(message.organization_id, delivery.event_id)
        if source is None:
            raise ServiceError(409, "outbox_delivery_integrity")
        return delivery, source

    def complete_notification_delivery(self, delivery: Delivery) -> None:
        if delivery.consumer != "notifications":
            raise ServiceError(422, "outbox_consumer_mismatch")
        self.store.save_delivery(delivery)


class EventCapture:
    """Capture source events and pin matching rules inside the business transaction."""

    def __init__(self, store: AutomationStore, audit: AuditWriter) -> None:
        self.store, self.audit = store, audit

    def capture(self, event: OperationalEvent) -> None:
        existing = self.store.event(event.organization_id, event.id)
        if existing:
            if existing != event:
                raise ServiceError(409, "outbox_event_conflict")
            return
        self.store.append(event)
        now = datetime.now(UTC)
        matches = self.store.matching(event)
        if len(matches) > 1000:
            raise ServiceError(422, "automation_match_limit")
        for version in matches:
            definition = version.definition
            if definition.form_id and (
                definition.form_id != event.payload.form_id
                or definition.form_number != event.payload.form_number
            ):
                continue
            if version.id in event.causation_path or len(event.causation_path) >= 16:
                continue
            if version.activator_id is None:
                raise ServiceError(409, "automation_delegation_missing")
            self.store.add_run(
                Run(
                    id=uuid7(),
                    organization_id=event.organization_id,
                    workspace_id=version.workspace_id,
                    rule_version_id=version.id,
                    event_id=event.id,
                    delegator_id=version.activator_id,
                    trigger_actor_id=event.actor_id,
                    correlation_id=event.correlation_id,
                    next_at=now,
                    created_at=now,
                )
            )
        self.store.add_delivery(
            Delivery(
                id=delivery_id(event.id, "automation"),
                organization_id=event.organization_id,
                event_id=event.id,
                consumer="automation",
                next_at=now,
            )
        )
        self.store.add_delivery(
            Delivery(
                id=delivery_id(event.id, "notifications"),
                organization_id=event.organization_id,
                event_id=event.id,
                consumer="notifications",
                next_at=now,
            )
        )
        self.audit.append(
            AuditEvent(
                id=uuid7(),
                type="outbox.event.captured",
                occurred_at=now,
                organization_id=event.organization_id,
                actor_id=event.actor_id,
                correlation_id=event.correlation_id,
                request_id=event.id,
                aggregate_type="outbox_event",
                aggregate_id=event.id,
                payload=AuditDetails(
                    workspace_id=event.workspace_id,
                    project_id=event.project_id,
                    target_id=event.aggregate_id,
                    reason="atomic_source_capture",
                ),
            )
        )
