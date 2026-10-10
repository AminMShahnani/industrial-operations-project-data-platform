from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5, uuid7

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.contracts import (
    AutomationAction,
    NotifyAction,
    Rule,
    Run,
)
from operations.modules.automation.application.events import OperationalEvent
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.identity.application.service import IdentityService
from operations.modules.notifications.application.contracts import (
    InboxItem,
    Notice,
    NoticeStore,
    ReadReceipt,
)
from operations.modules.notifications.application.email_contracts import EmailCapture
from operations.modules.notifications.application.sources import NoticeSources


class NotificationService:
    def __init__(
        self, store: NoticeStore, identity: IdentityService, sources: NoticeSources
    ) -> None:
        self.store, self.identity, self.sources = store, identity, sources
        self.email: EmailCapture | None = None

    def validate(self, actor: RequestContext, rule: Rule, action: AutomationAction) -> None:
        if not isinstance(action, NotifyAction):
            raise ServiceError(422, "automation_action_not_configured")
        if "email" in action.channels and self.email is None:
            raise ServiceError(422, "notification_channel_not_configured")
        if len(set(action.channels)) != len(action.channels):
            raise ServiceError(422, "notification_duplicate_channel")
        if "email" in action.channels:
            self.identity.authorization.require(
                actor,
                "organization.manage",
                Scope(rule.organization_id, ScopeType.ORGANIZATION, rule.organization_id),
            )
        if len(set(action.recipients)) != len(action.recipients):
            raise ServiceError(422, "notification_duplicate_recipient")
        for identifier in action.recipients:
            recipient = self.identity.active_context(rule.organization_id, identifier, actor)
            self.sources.forms.require(
                recipient,
                rule.organization_id,
                rule.workspace_id,
                rule.project_id,
                "project.read" if rule.project_id else "workspace.read",
            )

    def audit(self, actor: RequestContext, notice: Notice, action: str) -> None:
        user = self.identity.authorization.user(actor, notice.organization_id)
        self.identity.audit.append(
            AuditEvent(
                id=uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=notice.organization_id,
                actor_id=user.id,
                correlation_id=actor.correlation_id,
                request_id=actor.request_id,
                aggregate_type="notification",
                aggregate_id=notice.id,
                payload=AuditDetails(
                    workspace_id=notice.workspace_id,
                    project_id=notice.project_id,
                    target_id=notice.recipient_id,
                ),
            )
        )

    def execute(
        self,
        actor: RequestContext,
        rule: Rule,
        event: OperationalEvent,
        run: Run,
        position: int,
        action: AutomationAction,
    ) -> UUID | None:
        self.validate(actor, rule, action)
        assert isinstance(action, NotifyAction)
        if (event.organization_id, event.workspace_id, event.project_id) != (
            rule.organization_id,
            rule.workspace_id,
            rule.project_id,
        ) or (run.organization_id, run.event_id) != (event.organization_id, event.id):
            raise ServiceError(409, "notification_source_scope_mismatch")
        kind, source = self.sources.source(event)
        if (action.topic == "work_assigned" and kind != "task") or (
            action.topic == "review_requested" and kind != "workflow"
        ):
            raise ServiceError(422, "notification_topic_source_mismatch")
        # Resolve every recipient before writing anything; the run savepoint remains atomic.
        for identifier in action.recipients:
            recipient = self.identity.active_context(rule.organization_id, identifier, actor)
            self.sources.require(
                recipient, rule.organization_id, rule.workspace_id, rule.project_id, kind, source
            )
        for identifier in action.recipients:
            notice = Notice(
                id=uuid5(NAMESPACE_URL, f"operations:notice:{run.id}:{position}:{identifier}"),
                organization_id=rule.organization_id,
                workspace_id=rule.workspace_id,
                project_id=rule.project_id,
                recipient_id=identifier,
                event_id=event.id,
                run_id=run.id,
                position=position,
                topic=action.topic,
                source_kind=kind,
                source_id=source,
                created_at=datetime.now(UTC),
                in_app="in_app" in action.channels,
            )
            if self.store.get(rule.organization_id, identifier, notice.id) is None:
                self.audit(actor, notice, "notification.created")
                self.store.add(notice)
            if "email" in action.channels:
                assert self.email is not None
                self.email.queue(
                    actor,
                    rule.organization_id,
                    "notice",
                    notice.id,
                    identifier,
                    True,
                    "activated_notification_email",
                )
        return run.id

    def require(self, actor: RequestContext, notice: Notice) -> None:
        user = self.identity.authorization.user(actor, notice.organization_id)
        if user.id != notice.recipient_id:
            raise ServiceError(404, "notification_not_found")
        self.sources.require(
            actor,
            notice.organization_id,
            notice.workspace_id,
            notice.project_id,
            notice.source_kind,
            notice.source_id,
            notice.source_intent_id if notice.origin == "automatic" else None,
        )

    def inbox(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        after: UUID | None = None,
    ) -> tuple[list[InboxItem], UUID | None]:
        self.sources.forms.workspaces.active(org, workspace)
        user = self.identity.authorization.user(actor, org)
        rows = self.store.page(org, workspace, user.id, after)
        items: list[InboxItem] = []
        for notice in rows[:100]:
            try:
                self.require(actor, notice)
            except ServiceError as error:
                if error.status not in {403, 404}:
                    raise
                continue
            receipt = self.store.receipt(org, notice.id)
            items.append(InboxItem(notice=notice, read_at=receipt.read_at if receipt else None))
        return items, rows[99].id if len(rows) > 100 else None

    def mark_read(self, actor: RequestContext, org: UUID, identifier: UUID) -> ReadReceipt:
        user = self.identity.authorization.user(actor, org)
        notice = self.store.get(org, user.id, identifier, True)
        if notice is None or not notice.in_app:
            raise ServiceError(404, "notification_not_found")
        self.require(actor, notice)
        receipt = self.store.receipt(org, notice.id)
        if receipt:
            return receipt
        receipt = ReadReceipt(
            id=uuid7(),
            organization_id=org,
            notice_id=notice.id,
            recipient_id=user.id,
            read_at=datetime.now(UTC),
        )
        self.audit(actor, notice, "notification.read")
        self.store.add_receipt(receipt)
        return receipt

    def detail(
        self, actor: RequestContext, org: UUID, workspace: UUID, identifier: UUID
    ) -> InboxItem:
        user = self.identity.authorization.user(actor, org)
        notice = self.store.get(org, user.id, identifier)
        if notice is None or not notice.in_app or notice.workspace_id != workspace:
            raise ServiceError(404, "notification_not_found")
        self.require(actor, notice)
        receipt = self.store.receipt(org, notice.id)
        return InboxItem(notice=notice, read_at=receipt.read_at if receipt else None)
