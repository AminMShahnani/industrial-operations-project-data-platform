"""Anchored, bounded timer occurrences; activated definitions remain immutable."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid7

from operations.contracts import Command, ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.service import AutomationService
from operations.modules.iam.application.contracts import Scope, ScopeType
from operations.modules.identity.application.contracts import Principal, RequestContext


class TimerOccurrence(Command):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    rule_version_id: UUID
    scheduled_at: datetime


class TimerTick(Command):
    candidates: int
    created: int
    more: bool
    next_at: datetime


class TimerStore(Protocol):
    def last(self, org: UUID, version: UUID) -> datetime | None: ...
    def add(self, row: TimerOccurrence) -> None: ...


def first_slot(start: datetime, activated: datetime, seconds: int) -> datetime:
    start = start.astimezone(UTC)
    step = timedelta(seconds=seconds)
    index = max(0, (activated - start) // step)
    slot = start + index * step
    return slot + step if slot < activated else slot


class TimerService:
    def __init__(self, store: TimerStore, automation: AutomationService) -> None:
        self.store, self.automation = store, automation

    def tick(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        dry_run: bool = True,
        *,
        now: datetime | None = None,
    ) -> TimerTick:
        now = now or datetime.now(UTC)
        if now.utcoffset() is None:
            raise ServiceError(422, "timer_timezone_required")
        rule = self.automation.get(actor, org, workspace, identifier, True)
        if rule.active_number is None:
            raise ServiceError(409, "timer_rule_not_active")
        _, version = self.automation.version(
            actor, org, workspace, identifier, rule.active_number, True
        )
        definition = version.definition
        if (
            version.state != "active"
            or definition.trigger != "scheduled.timer"
            or version.activated_at is None
            or version.activator_id is None
            or definition.timer_start is None
            or definition.timer_seconds is None
        ):
            raise ServiceError(422, "timer_definition_required")
        # Recheck both operator and delegator; a timer never acquires system authority.
        user = self.automation.forms.authorization.identities.by_id(org, version.activator_id)
        if user is None or not user.active:
            raise ServiceError(403, "automation_delegation_revoked")
        delegated = RequestContext(
            Principal(user.issuer, user.subject), actor.request_id, actor.correlation_id
        )
        self.automation.forms.authorization.require(
            delegated, "organization.manage", Scope(org, ScopeType.ORGANIZATION, org)
        )
        self.automation.require(delegated, org, workspace, rule.project_id, True)
        last = self.store.last(org, version.id)
        step = timedelta(seconds=definition.timer_seconds)
        slot = (
            last + step
            if last
            else first_slot(definition.timer_start, version.activated_at, definition.timer_seconds)
        )
        total = max(0, (now - slot) // step + 1)
        count = min(total, 100)
        for _ in range(count):
            if not dry_run:
                occurrence = TimerOccurrence(
                    id=uuid7(),
                    organization_id=org,
                    workspace_id=workspace,
                    rule_version_id=version.id,
                    scheduled_at=slot,
                )
                operator = self.automation.forms.authorization.user(actor, org)
                self.automation.audit.append(
                    AuditEvent(
                        id=occurrence.id,
                        type="timer.fired",
                        occurred_at=datetime.now(UTC),
                        organization_id=org,
                        actor_id=operator.id,
                        correlation_id=actor.correlation_id,
                        request_id=actor.request_id,
                        aggregate_type="timer",
                        aggregate_id=version.id,
                        payload=AuditDetails(
                            workspace_id=workspace,
                            project_id=rule.project_id,
                            timer_version_id=version.id,
                            scheduled_at=slot,
                            form_id=definition.form_id,
                            form_number=definition.form_number,
                        ),
                    )
                )
                self.store.add(occurrence)
            slot += step
        return TimerTick(
            candidates=count, created=0 if dry_run else count, more=total > 100, next_at=slot
        )
