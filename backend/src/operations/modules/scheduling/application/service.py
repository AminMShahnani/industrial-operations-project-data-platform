import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7
from zoneinfo import ZoneInfo

from operations.contracts import ServiceError
from operations.modules.audit.application.contracts import AuditDetails, AuditEvent
from operations.modules.automation.application.events import EventContext
from operations.modules.forms.application.contracts import Cell
from operations.modules.forms.application.service import FormService
from operations.modules.identity.application.contracts import Principal, RequestContext, User
from operations.modules.projects.application.contracts import Milestone
from operations.modules.scheduling.application.contracts import (
    Assignment,
    Schedule,
    ScheduleDefinition,
    ScheduleStore,
    ScheduleVersion,
    Shift,
    Trigger,
)
from operations.modules.scheduling.domain.recurrence import (
    expand,
    intervals,
    local_instant,
    parse_rule,
    validate_window,
)


class SchedulingService:
    def __init__(self, store: ScheduleStore, forms: FormService) -> None:
        self.store, self.forms = store, forms

    def event(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        action: str,
        reason: str | None = None,
        *,
        project: UUID | None = None,
        source: EventContext | None = None,
        event_id: UUID | None = None,
    ) -> None:
        user = self.forms.authorization.user(actor, org)
        self.forms.audit.append(
            AuditEvent(
                id=event_id or uuid7(),
                type=action,
                occurred_at=datetime.now(UTC),
                organization_id=org,
                actor_id=user.id,
                request_id=actor.request_id,
                correlation_id=actor.correlation_id,
                aggregate_type=action.split(".")[0],
                aggregate_id=identifier,
                payload=AuditDetails(
                    scope_type="project" if project else "workspace",
                    scope_id=project or workspace,
                    reason=reason,
                    workspace_id=workspace,
                    project_id=project,
                    **(source.model_dump() if source else {}),
                ),
            )
        )

    def require(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        manage: bool = False,
    ) -> None:
        self.forms.require(
            actor, org, workspace, project, "schedule.manage" if manage else "task.read", manage
        )

    def get(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        manage: bool = False,
    ) -> Schedule:
        self.forms.authorization.user(actor, org)
        row = self.store.get(org, workspace, identifier)
        if row is None:
            raise ServiceError(404, "not_found")
        self.require(actor, org, workspace, row.project_id, manage)
        return row

    def create(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        name: str,
        definition: ScheduleDefinition,
    ) -> Schedule:
        self.require(actor, org, workspace, project, True)
        self.check(actor, org, workspace, project, definition)
        row = Schedule(
            id=uuid7(), organization_id=org, workspace_id=workspace, project_id=project, name=name
        )
        self.store.create(row)
        self.store.add_version(
            ScheduleVersion(
                id=uuid7(),
                organization_id=org,
                workspace_id=workspace,
                schedule_id=row.id,
                number=1,
                definition=definition,
            )
        )
        self.event(actor, org, workspace, row.id, "schedule.created")
        return row

    def check(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        definition: ScheduleDefinition,
    ) -> tuple[UUID, dict[str, list[UUID]]]:
        form, version = self.forms.version(
            actor, org, workspace, definition.form_id, definition.form_number
        )
        if form.project_id != project or version.state != "published":
            raise ServiceError(422, "schedule_form_scope_or_state")
        recurrence = definition.recurrence
        if recurrence.shift_id:
            shift = self.store.shift(org, workspace, recurrence.shift_id)
            if not shift or shift.project_id != project or shift.timezone != recurrence.timezone:
                raise ServiceError(422, "shift_scope_mismatch")
        if recurrence.milestone_id and (
            project is None
            or self.forms.projects.milestone(org, workspace, project, recurrence.milestone_id)
            is None
        ):
            raise ServiceError(422, "milestone_scope_mismatch")
        recipients = {
            item.key(): self.recipients(actor, org, workspace, project, item)
            for item in definition.assignments
        }
        if any(not values for values in recipients.values()):
            raise ServiceError(422, "assignment_has_no_eligible_recipients")
        return version.id, recipients

    def eligible(
        self, actor: RequestContext, org: UUID, workspace: UUID, project: UUID | None, user: User
    ) -> bool:
        try:
            context = RequestContext(
                Principal(user.issuer, user.subject), actor.request_id, actor.correlation_id
            )
            return user.active and "task.execute" in self.forms.permissions(
                context, org, workspace, project
            )
        except ServiceError:
            return False

    def recipients(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        target: Assignment,
    ) -> list[UUID]:
        ids: set[UUID] | None = None
        if target.kind == "user":
            ids = {target.target_id} if target.target_id else set()
        elif target.kind in {"team", "department"}:
            if target.target_id is None:
                raise ServiceError(422, "missing_assignment_target")
            group = self.forms.groups.get(org, workspace, target.target_id)
            if not group.active or group.kind.value != target.kind:
                raise ServiceError(422, "assignment_group_kind")
        elif target.kind == "shift":
            shift = self.store.shift(org, workspace, target.target_id) if target.target_id else None
            if not shift or shift.project_id != project:
                raise ServiceError(422, "assignment_shift_scope")
            ids = set(shift.user_ids)
        output: list[UUID] = []
        after: UUID | None = None
        while True:
            users = self.forms.authorization.identities.active_users(org, after)
            for user in users[:100]:
                if ids is not None and user.id not in ids:
                    continue
                if target.kind in {"team", "department"} and not any(
                    member.group_id == target.target_id
                    for member in self.forms.groups.store.memberships(org, workspace, user.id)
                ):
                    continue
                if target.kind == "role" and not self.has_role(
                    actor, org, workspace, project, user, str(target.role)
                ):
                    continue
                if self.eligible(actor, org, workspace, project, user):
                    output.append(user.id)
                if len(output) > 1000:
                    raise ServiceError(422, "assignment_recipient_limit")
            if len(users) <= 100:
                return sorted(output)
            after = users[99].id

    def has_role(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        user: User,
        role: str,
    ) -> bool:
        now = datetime.now(UTC)
        grants = self.forms.authorization.grants.for_user(org, user.id)
        if any(
            not g.revoked
            and str(g.role) == role
            and (g.valid_from is None or g.valid_from <= now)
            and (g.valid_until is None or now < g.valid_until)
            and ((g.scope_id == workspace and project is None) or (g.scope_id == org and g.inherit))
            for g in grants
        ):
            return True
        if project:
            from operations.modules.projects.application.service import effective

            if any(
                member.project_id == project and str(member.role) == role and effective(member, now)
                for member in self.forms.projects.store.memberships(org, user.id)
            ):
                return True
            departments = self.forms.groups.departments_for_user(org, workspace, user.id)
            return any(
                grant.project_id == project and str(grant.role) == role and effective(grant, now)
                for grant in self.forms.projects.store.department_grants(org, departments)
            )
        return False

    def version(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        manage: bool = False,
    ) -> tuple[Schedule, ScheduleVersion]:
        schedule = self.get(actor, org, workspace, identifier, manage)
        row = self.store.version(org, identifier, number)
        if not row:
            raise ServiceError(404, "not_found")
        if row.state == "draft":
            self.require(actor, org, workspace, schedule.project_id, True)
        return schedule, row

    def save(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        definition: ScheduleDefinition,
    ) -> ScheduleVersion:
        schedule, row = self.version(actor, org, workspace, identifier, number, True)
        if row.state != "draft":
            raise ServiceError(409, "immutable_schedule")
        self.check(actor, org, workspace, schedule.project_id, definition)
        changed = row.model_copy(update={"definition": definition, "revision": row.revision + 1})
        if not self.store.save_version(changed, expected):
            raise ServiceError(409, "stale_revision")
        self.event(actor, org, workspace, row.id, "schedule.draft.updated")
        return changed

    def clone(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        source: int,
        number: int,
    ) -> ScheduleVersion:
        _, row = self.version(actor, org, workspace, identifier, source, True)
        if number <= source or self.store.version(org, identifier, number):
            raise ServiceError(409, "schedule_version_conflict")
        result = ScheduleVersion(
            id=uuid7(),
            organization_id=org,
            workspace_id=workspace,
            schedule_id=identifier,
            number=number,
            definition=row.definition,
        )
        self.store.add_version(result)
        self.event(actor, org, workspace, result.id, "schedule.version.created")
        return result

    def activation_plan(
        self, actor: RequestContext, schedule: Schedule, row: ScheduleVersion
    ) -> tuple[str, UUID]:
        form, recipients = self.check(
            actor,
            schedule.organization_id,
            schedule.workspace_id,
            schedule.project_id,
            row.definition,
        )
        payload = {
            "definition": row.definition.model_dump(mode="json"),
            "form_version_id": str(form),
            "recipients": {key: [str(x) for x in values] for key, values in recipients.items()},
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(), form

    def activate(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        dry_run: bool,
        sha: str | None,
    ) -> ScheduleVersion:
        schedule, row = self.version(actor, org, workspace, identifier, number, True)
        if (
            row.state != "draft"
            or row.revision != expected
            or (schedule.active_number is not None and number <= schedule.active_number)
        ):
            raise ServiceError(409, "schedule_activation_conflict")
        digest, form = self.activation_plan(actor, schedule, row)
        planned = row.model_copy(update={"form_version_id": form, "content_sha256": digest})
        if dry_run:
            return planned
        if sha != digest:
            raise ServiceError(409, "activation_preview_changed")
        changed = planned.model_copy(
            update={
                "state": "active",
                "activated_at": datetime.now(UTC),
                "revision": row.revision + 1,
            }
        )
        if schedule.active_number is not None:
            previous = self.store.version(org, identifier, schedule.active_number)
            if previous and previous.state == "active":
                paused = previous.model_copy(
                    update={"state": "paused", "revision": previous.revision + 1}
                )
                if not self.store.save_version(paused, previous.revision):
                    raise ServiceError(409, "stale_revision")
                self.event(actor, org, workspace, previous.id, "schedule.version.superseded")
        if not self.store.save_version(changed, expected) or not self.store.update(
            schedule.model_copy(
                update={"active_number": number, "revision": schedule.revision + 1}
            ),
            schedule.revision,
        ):
            raise ServiceError(409, "stale_revision")
        self.event(actor, org, workspace, row.id, "schedule.version.activated")
        return changed

    def lifecycle(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        number: int,
        expected: int,
        state: str,
        reason: str,
        dry_run: bool,
    ) -> ScheduleVersion:
        schedule, row = self.version(actor, org, workspace, identifier, number, True)
        if (
            schedule.active_number != number
            or row.revision != expected
            or (row.state, state)
            not in {
                ("active", "paused"),
                ("paused", "active"),
                ("active", "retired"),
                ("paused", "retired"),
            }
        ):
            raise ServiceError(409, "invalid_schedule_transition")
        changed = ScheduleVersion.model_validate(
            row.model_dump() | {"state": state, "revision": row.revision + 1}
        )
        if not dry_run:
            if not self.store.save_version(changed, expected):
                raise ServiceError(409, "stale_revision")
            self.event(actor, org, workspace, row.id, "schedule.version." + state, reason)
        return changed

    def timestamps(
        self, schedule: Schedule, version: ScheduleVersion, start: datetime, end: datetime
    ) -> list[datetime]:
        recurrence = version.definition.recurrence
        try:
            validate_window(start, end)
            if recurrence.kind == "one_time" and recurrence.at:
                return [recurrence.at.astimezone(UTC)] if start <= recurrence.at < end else []
            if recurrence.kind == "interval" and recurrence.at and recurrence.interval_seconds:
                return intervals(recurrence.at, recurrence.interval_seconds, start, end)
            if recurrence.kind == "milestone" and recurrence.milestone_id and schedule.project_id:
                milestone = self.forms.projects.milestone(
                    schedule.organization_id,
                    schedule.workspace_id,
                    schedule.project_id,
                    recurrence.milestone_id,
                )
                if not milestone:
                    raise ServiceError(409, "missing_milestone")
                at = milestone.planned_at + timedelta(seconds=recurrence.offset_seconds)
                return [at] if start <= at < end else []
            if recurrence.kind == "relative_event" and recurrence.event_code:
                offset = timedelta(seconds=recurrence.offset_seconds)
                events = self.store.triggers(
                    schedule.organization_id,
                    schedule.workspace_id,
                    schedule.project_id,
                    recurrence.event_code,
                    start - offset,
                    end - offset,
                )
                if len(events) > 2000:
                    raise ServiceError(422, "trigger_limit")
                return sorted({event.occurred_at + offset for event in events})
            local = recurrence.starts_local
            if local:
                if recurrence.kind == "shift" and recurrence.shift_id:
                    shift = self.store.shift(
                        schedule.organization_id, schedule.workspace_id, recurrence.shift_id
                    )
                    if shift is None:
                        raise ServiceError(409, "missing_shift")
                    local = datetime.combine(local.date(), shift.starts_at)
                return expand(
                    local,
                    recurrence.timezone,
                    parse_rule(
                        recurrence.rule
                        or "FREQ="
                        + ("DAILY" if recurrence.kind == "shift" else recurrence.kind.upper())
                    ),
                    start,
                    end,
                )
            raise ValueError("Unsupported recurrence")
        except ValueError as error:
            raise ServiceError(422, "invalid_recurrence_window") from error

    def add_shift(self, actor: RequestContext, row: Shift) -> Shift:
        self.require(actor, row.organization_id, row.workspace_id, row.project_id, True)
        for identifier in row.user_ids:
            user = self.forms.authorization.identities.by_id(row.organization_id, identifier)
            if not user or not self.eligible(
                actor, row.organization_id, row.workspace_id, row.project_id, user
            ):
                raise ServiceError(422, "shift_recipient_ineligible")
        self.store.add_shift(row)
        self.event(actor, row.organization_id, row.workspace_id, row.id, "shift.created")
        return row

    def add_milestone(self, actor: RequestContext, row: Milestone) -> Milestone:
        self.require(actor, row.organization_id, row.workspace_id, row.project_id, True)
        return self.forms.projects.add_milestone(actor, row)

    def add_trigger(self, actor: RequestContext, row: Trigger) -> Trigger:
        self.require(actor, row.organization_id, row.workspace_id, row.project_id, True)
        if self.store.add_trigger(row):
            self.event(
                actor, row.organization_id, row.workspace_id, row.id, "schedule_trigger.recorded"
            )
        else:
            matches = self.store.triggers(
                row.organization_id,
                row.workspace_id,
                row.project_id,
                row.code,
                row.occurred_at,
                row.occurred_at + timedelta(microseconds=1),
            )
            if not any(item == row for item in matches):
                raise ServiceError(409, "trigger_idempotency_conflict")
        return row


class SchedulingDefaults:
    def __init__(self, store: ScheduleStore) -> None:
        self.store = store

    def shift(
        self, organization_id: UUID, workspace_id: UUID, project_id: UUID | None, user_id: UUID
    ) -> str | None:
        now = datetime.now(UTC)
        found: list[Shift] = []
        after: UUID | None = None
        latest: dict[str, Shift] = {}
        while True:
            rows = self.store.shifts(organization_id, workspace_id, project_id, after)
            for row in rows[:100]:
                if row.code not in latest or row.number > latest[row.code].number:
                    latest[row.code] = row
            if len(rows) <= 100:
                break
            after = rows[99].id
        for row in latest.values():
            if user_id not in row.user_ids:
                continue
            local = now.astimezone(ZoneInfo(row.timezone))
            for date in (local.date(), local.date() - timedelta(days=1)):
                start = local_instant(datetime.combine(date, row.starts_at), row.timezone)
                if start and start <= now < start + timedelta(seconds=row.duration_seconds):
                    found.append(row)
        return str(found[0].id) if len(found) == 1 else None

    def previous_approved(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        form_id: UUID,
        owner_id: UUID,
        field_key: str,
    ) -> Cell:
        return None  # Workflow's authoritative provider belongs to Phase 5.
