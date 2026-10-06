"""Bounded reconciliation of exact retained intents, without inferred historical events."""

import hashlib
import json
from datetime import datetime
from uuid import UUID

from pydantic import Field

from operations.contracts import Command, ServiceError
from operations.modules.automation.application.events import HandoffKind
from operations.modules.automation.application.service import AutomationService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.tasks.application.service import TaskService
from operations.modules.workflows.application.runtime import WorkflowRuntime


class HandoffReviewItem(Command):
    intent_id: UUID
    source_id: UUID
    project_id: UUID | None
    source_created_at: datetime
    recipient_count: int = Field(ge=0, le=1000)
    existing_event_id: UUID | None


class HandoffReview(Command):
    organization_id: UUID
    workspace_id: UUID
    kind: HandoffKind
    after: UUID | None
    items: list[HandoffReviewItem] = Field(max_length=100)
    cursor: UUID | None
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created: int = Field(default=0, ge=0, le=100)
    applied: bool = False


class NotificationReconciler:
    def __init__(
        self, automation: AutomationService, tasks: TaskService, workflows: WorkflowRuntime
    ) -> None:
        self.automation, self.tasks, self.workflows = automation, tasks, workflows

    def reconcile(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        kind: HandoffKind,
        after: UUID | None = None,
        *,
        dry_run: bool = True,
        review_sha256: str | None = None,
        reason: str | None = None,
    ) -> HandoffReview:
        self.automation.forms.authorization.require(
            actor, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        )
        if kind == "task_reminder":
            rows = self.tasks.notification_handoffs(actor, org, workspace, after)
        elif kind == "workflow_notify":
            rows = self.workflows.notification_handoffs(actor, org, workspace, after)
        else:
            raise ServiceError(422, "notification_handoff_kind_invalid")
        cursor = rows[99].intent_id if len(rows) > 100 else None
        selected = rows[:100]
        events = [self.automation.notification_handoff_event(row) for row in selected]
        items = [
            HandoffReviewItem(
                intent_id=row.intent_id,
                source_id=row.source_id,
                project_id=row.project_id,
                source_created_at=row.created_at,
                recipient_count=len(row.recipient_ids),
                existing_event_id=event.id if event is not None else None,
            )
            for row, event in zip(selected, events, strict=True)
        ]
        content = {
            "org": str(org),
            "workspace": str(workspace),
            "kind": kind,
            "after": str(after) if after else None,
            "cursor": str(cursor) if cursor else None,
            "sources": [row.model_dump(mode="json") for row in selected],
            "events": [item.model_dump(mode="json") for item in items],
        }
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        created = 0
        if not dry_run:
            if digest != review_sha256:
                raise ServiceError(409, "notification_handoff_review_required")
            if reason is None or not reason.strip() or len(reason) > 500:
                raise ServiceError(422, "notification_handoff_reason_required")
            for row, event in zip(selected, events, strict=True):
                if event is None:
                    self.automation.capture_notification_handoff(actor, row, reason.strip())
                    created += 1
        return HandoffReview(
            organization_id=org,
            workspace_id=workspace,
            kind=kind,
            after=after,
            items=items,
            cursor=cursor,
            review_sha256=digest,
            created=created,
            applied=not dry_run,
        )
