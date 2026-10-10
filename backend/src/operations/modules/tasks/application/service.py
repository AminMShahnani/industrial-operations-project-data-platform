from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5, uuid7
from zoneinfo import ZoneInfo

from operations.contracts import ServiceError
from operations.modules.automation.application.events import EventContext, NotificationHandoff
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.scheduling.application.service import SchedulingService
from operations.modules.submissions.application.contracts import Submission
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.tasks.application.contracts import (
    DeadlineEvent,
    DeadlineTick,
    GenericTaskDefinition,
    Reminder,
    Task,
    TaskStore,
)


class TaskService:
    def __init__(
        self, store: TaskStore, schedules: SchedulingService, submissions: SubmissionService
    ) -> None:
        self.store, self.schedules, self.submissions = store, schedules, submissions

    def generic_recipients(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        definition: GenericTaskDefinition,
    ) -> dict[str, list[UUID]]:
        self.schedules.require(actor, org, workspace, project, True)
        recipients = {
            item.key(): self.schedules.recipients(actor, org, workspace, project, item)
            for item in definition.assignments
        }
        if any(not users for users in recipients.values()):
            raise ServiceError(422, "assignment_has_no_eligible_recipients")
        return recipients

    def create_generic(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        definition: GenericTaskDefinition,
    ) -> list[Task]:
        recipients = self.generic_recipients(actor, org, workspace, project, definition)
        timezone = self.schedules.forms.workspaces.organizations.active(org).settings.timezone
        rows: list[Task] = []
        for target in definition.assignments:
            identifier = uuid5(definition.origin_id, target.key())
            existing = self.store.get(org, workspace, identifier)
            if existing:
                if (
                    existing.kind != "generic"
                    or existing.project_id != project
                    or existing.name != definition.name
                    or existing.assignment != target
                    or existing.occurs_at != definition.occurs_at
                    or existing.due_at
                    != definition.occurs_at + timedelta(seconds=definition.due_seconds)
                ):
                    raise ServiceError(409, "task_creation_conflict")
                rows.append(existing)
                continue
            row = Task(
                id=identifier,
                organization_id=org,
                workspace_id=workspace,
                project_id=project,
                kind="generic",
                origin_id=definition.origin_id,
                name=definition.name,
                timezone=timezone,
                occurs_at=definition.occurs_at,
                due_at=definition.occurs_at + timedelta(seconds=definition.due_seconds),
                assignment=target,
                assignment_key=target.key(),
                recipient_ids=recipients[target.key()],
                reminder_offsets=[],
            )
            if not self.store.add(row):
                raise ServiceError(409, "task_creation_conflict")
            self.event(actor, row, "task.created")
            rows.append(row)
        return rows

    def complete(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
    ) -> Task:
        row = self.access(actor, org, workspace, identifier, True)
        user = self.schedules.forms.authorization.user(actor, org)
        if row.kind != "generic":
            raise ServiceError(409, "form_task_completion_requires_submission")
        if row.claimant_id != user.id:
            raise ServiceError(403, "task_claimant_required")
        if row.state == "completed":
            return row
        if row.state != "in_progress" or row.revision != expected:
            raise ServiceError(409, "task_completion_conflict")
        changed = row.model_copy(
            update={
                "state": "completed",
                "completed_at": datetime.now(UTC),
                "revision": row.revision + 1,
            }
        )
        if not self.store.save(changed, expected):
            raise ServiceError(409, "task_completion_conflict")
        self.event(actor, changed, "task.completed")
        return changed

    def event(
        self,
        actor: RequestContext,
        row: Task,
        action: str,
        reason: str | None = None,
        *,
        event_id: UUID | None = None,
        scheduled_at: datetime | None = None,
        reminder_id: UUID | None = None,
        include_submission: bool = True,
    ) -> None:
        self.schedules.event(
            actor,
            row.organization_id,
            row.workspace_id,
            row.id,
            action,
            reason,
            project=row.project_id,
            event_id=event_id,
            source=EventContext(
                form_id=row.form_id,
                form_number=row.form_number,
                task_id=row.id,
                recipient_ids=row.recipient_ids,
                subject_user_id=row.claimant_id,
                submission_id=row.submission_id if include_submission else None,
                scheduled_at=scheduled_at,
                reminder_id=reminder_id,
            ),
        )

    def generate_deadlines(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        after: UUID | None = None,
        dry_run: bool = True,
        *,
        now: datetime | None = None,
    ) -> DeadlineTick:
        self.schedules.require(actor, org, workspace, project, True)
        now = now or datetime.now(UTC)
        if now.utcoffset() is None:
            raise ServiceError(422, "deadline_timezone_required")
        rows = self.store.deadline_candidates(org, workspace, project, now, after, not dry_run)
        candidates = created = 0
        for row in rows[:100]:
            seen = self.store.deadline_kinds(org, workspace, row.id)
            for kind in ("due", "overdue"):
                if kind in seen or (kind == "overdue" and row.due_at >= now):
                    continue
                candidates += 1
                if dry_run:
                    continue
                event = DeadlineEvent(
                    id=uuid7(),
                    organization_id=org,
                    workspace_id=workspace,
                    task_id=row.id,
                    kind=kind,
                    scheduled_at=row.due_at,
                )
                self.event(
                    actor,
                    row,
                    "task." + kind,
                    event_id=event.id,
                    scheduled_at=row.due_at,
                    include_submission=False,
                )
                if not self.store.add_deadline(event):
                    raise ServiceError(409, "deadline_event_conflict")
                created += 1
        return DeadlineTick(
            candidates=candidates, created=created, cursor=rows[99].id if len(rows) > 100 else None
        )

    def access(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        execute: bool = False,
        *,
        scope_write: bool = True,
    ) -> Task:
        user = self.schedules.forms.authorization.user(actor, org)
        row = self.store.get(org, workspace, identifier)
        if not row:
            raise ServiceError(404, "not_found")
        self.schedules.require(actor, org, workspace, row.project_id)
        permissions = self.schedules.forms.permissions(actor, org, workspace, row.project_id)
        if user.id not in row.recipient_ids and "schedule.manage" not in permissions:
            raise ServiceError(403, "task_not_assigned")
        if execute:
            self.schedules.forms.require(
                actor, org, workspace, row.project_id, "task.execute", scope_write
            )
            if user.id not in row.recipient_ids:
                raise ServiceError(403, "task_not_assigned")
            if row.assignment.kind in {"team", "department"}:
                group = (
                    self.schedules.forms.groups.get(org, workspace, row.assignment.target_id)
                    if row.assignment.target_id
                    else None
                )
                if (
                    not group
                    or not group.active
                    or not any(
                        member.group_id == group.id
                        for member in self.schedules.forms.groups.store.memberships(
                            org, workspace, user.id
                        )
                    )
                ):
                    raise ServiceError(403, "task_assignment_revoked")
            if row.assignment.kind == "role" and not self.schedules.has_role(
                actor, org, workspace, row.project_id, user, str(row.assignment.role)
            ):
                raise ServiceError(403, "task_assignment_revoked")
        return row

    def public(self, actor: RequestContext, row: Task) -> Task:
        user = self.schedules.forms.authorization.user(actor, row.organization_id)
        manager = "schedule.manage" in self.schedules.forms.permissions(
            actor, row.organization_id, row.workspace_id, row.project_id
        )

        return (
            row
            if manager
            else row.model_copy(
                update={
                    "recipient_ids": [user.id],
                    "submission_id": row.submission_id if row.claimant_id == user.id else None,
                }
            )
        )

    def notification_handoffs(
        self, actor: RequestContext, org: UUID, workspace: UUID, after: UUID | None
    ) -> list[NotificationHandoff]:
        self.schedules.forms.require(actor, org, workspace, None, "automation.manage")
        rows: list[NotificationHandoff] = []
        for reminder in self.store.reminder_intents(org, workspace, after):
            task = self.store.get(org, workspace, reminder.task_id)
            if task is None:
                raise ServiceError(409, "notification_handoff_source_integrity")
            self.schedules.forms.require(
                actor, org, workspace, task.project_id, "automation.manage"
            )
            rows.append(
                NotificationHandoff(
                    kind="task_reminder",
                    intent_id=reminder.id,
                    organization_id=org,
                    workspace_id=workspace,
                    project_id=task.project_id,
                    source_id=task.id,
                    recipient_ids=task.recipient_ids,
                    created_at=reminder.created_at,
                    scheduled_at=reminder.scheduled_at,
                )
            )
        return rows

    def notification_delivery_access(
        self, actor: RequestContext, org: UUID, workspace: UUID, identifier: UUID
    ) -> None:
        row = self.access(actor, org, workspace, identifier, True, scope_write=False)
        if row.state not in {"open", "in_progress", "returned"}:
            raise ServiceError(403, "notification_task_no_longer_pending")
        if row.project_id:
            project = self.schedules.forms.projects.require_access(
                actor, org, workspace, row.project_id, "project.read"
            )
            if project.state in project.lifecycle.terminal:
                raise ServiceError(403, "notification_project_no_longer_active")

    def materialize(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        start: datetime,
        end: datetime,
        dry_run: bool = True,
    ) -> tuple[int, int]:
        schedule = self.schedules.get(actor, org, workspace, identifier, True)
        if not schedule.active_number:
            raise ServiceError(409, "schedule_not_active")
        _, version = self.schedules.version(
            actor, org, workspace, identifier, schedule.active_number, True
        )
        if version.state != "active" or version.form_version_id is None:
            raise ServiceError(409, "schedule_not_active")
        _, live = self.schedules.forms.version(
            actor, org, workspace, version.definition.form_id, version.definition.form_number
        )
        if live.id != version.form_version_id or live.state != "published":
            raise ServiceError(409, "scheduled_form_not_active")
        times = self.schedules.timestamps(schedule, version, start, end)
        if len(times) * len(version.definition.assignments) > 2000:
            raise ServiceError(422, "materialization_limit")
        recipients = {
            target.key(): self.schedules.recipients(
                actor, org, workspace, schedule.project_id, target
            )
            for target in version.definition.assignments
        }
        created = 0
        for at in times:
            for target in version.definition.assignments:
                if not recipients[target.key()]:
                    continue
                task = Task(
                    id=uuid7(),
                    organization_id=org,
                    workspace_id=workspace,
                    project_id=schedule.project_id,
                    schedule_id=identifier,
                    schedule_version_id=version.id,
                    schedule_number=version.number,
                    form_id=version.definition.form_id,
                    form_version_id=version.form_version_id,
                    form_number=version.definition.form_number,
                    name=schedule.name,
                    timezone=version.definition.recurrence.timezone,
                    occurs_at=at,
                    due_at=at + timedelta(seconds=version.definition.due_after_seconds),
                    assignment=target,
                    assignment_key=target.key(),
                    recipient_ids=recipients[target.key()],
                    reminder_offsets=version.definition.reminder_offsets,
                )
                if not dry_run and self.store.add(task):
                    created += 1
                    self.event(actor, task, "task.created")
        return len(times) * len(version.definition.assignments), created

    def supersede(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        schedule_id: UUID,
        number: int,
        dry_run: bool = False,
    ) -> int:
        self.schedules.get(actor, org, workspace, schedule_id, True)
        rows = self.store.future_open(org, workspace, schedule_id, number, datetime.now(UTC))
        if len(rows) > 2000:
            raise ServiceError(422, "supersession_limit")
        if not dry_run:
            for row in rows:
                changed = row.model_copy(
                    update={"state": "superseded", "revision": row.revision + 1}
                )
                if not self.store.save(changed, row.revision):
                    raise ServiceError(409, "stale_revision")
                self.event(actor, row, "task.superseded")
        return len(rows)

    def claim(
        self, actor: RequestContext, org: UUID, workspace: UUID, identifier: UUID, expected: int
    ) -> Task:
        row = self.access(actor, org, workspace, identifier, True)
        user = self.schedules.forms.authorization.user(actor, org)
        if row.state == "in_progress" and row.claimant_id == user.id:
            return row
        if row.state != "open" or row.revision != expected:
            raise ServiceError(409, "task_claim_conflict")
        submission_id = None
        if row.kind == "form":
            if row.form_id is None or row.form_number is None:
                raise ServiceError(409, "task_form_version_mismatch")
            draft = self.submissions.create(actor, org, workspace, row.form_id, row.form_number)
            if draft.form_version_id != row.form_version_id:
                raise ServiceError(409, "task_form_version_mismatch")
            submission_id = draft.id
        changed = row.model_copy(
            update={
                "state": "in_progress",
                "claimant_id": user.id,
                "submission_id": submission_id,
                "revision": row.revision + 1,
            }
        )
        if not self.store.save(changed, expected):
            raise ServiceError(409, "task_claim_conflict")
        self.event(actor, changed, "task.claimed")
        return changed

    def submitted(self, actor: RequestContext, submission: Submission) -> None:
        row = self.store.by_submission(
            submission.organization_id, submission.workspace_id, submission.id
        )
        if not row:
            return
        self.access(actor, row.organization_id, row.workspace_id, row.id, True)
        if (
            row.claimant_id != submission.owner_id
            or row.form_version_id != submission.form_version_id
            or row.state != "in_progress"
        ):
            raise ServiceError(409, "task_submission_conflict")
        changed = row.model_copy(update={"state": "submitted", "revision": row.revision + 1})
        if not self.store.save(changed, row.revision):
            raise ServiceError(409, "stale_revision")
        self.event(actor, row, "task.submitted")

    def validate_write(self, actor: RequestContext, submission: Submission) -> None:
        row = self.store.by_submission(
            submission.organization_id, submission.workspace_id, submission.id
        )
        if row:
            self.access(actor, row.organization_id, row.workspace_id, row.id, True)
            if row.state != "in_progress" or row.claimant_id != submission.owner_id:
                raise ServiceError(409, "task_not_writable")

    def validate_revision_write(
        self, actor: RequestContext, org: UUID, workspace: UUID, root: UUID
    ) -> None:
        row = self.store.by_submission(org, workspace, root)
        if row:
            self.access(actor, org, workspace, row.id, True)
            user = self.schedules.forms.authorization.user(actor, org)
            if row.claimant_id != user.id or row.state not in {"returned", "approved", "submitted"}:
                raise ServiceError(409, "task_revision_not_writable")

    def workflow_transition(
        self, actor: RequestContext, org: UUID, workspace: UUID, root: UUID, state: str
    ) -> None:
        self.schedules.forms.authorization.user(actor, org)
        row = self.store.by_submission(org, workspace, root)
        if row is None or row.state == state:
            return
        if state not in {"awaiting_review", "returned", "approved", "submitted"}:
            raise ServiceError(422, "invalid_workflow_task_state")
        if row.state not in {"submitted", "awaiting_review", "returned", "approved"}:
            raise ServiceError(409, "task_workflow_conflict")
        changed = row.model_copy(update={"state": state, "revision": row.revision + 1})
        if not self.store.save(changed, row.revision):
            raise ServiceError(409, "stale_revision")
        self.event(actor, changed, "task.workflow." + state)

    def cancel(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        expected: int,
        reason: str,
        dry_run: bool,
    ) -> Task:
        row = self.access(actor, org, workspace, identifier)
        self.schedules.require(actor, org, workspace, row.project_id, True)
        if row.revision != expected or row.state not in {"open", "in_progress"}:
            raise ServiceError(409, "task_cancellation_conflict")
        changed = row.model_copy(update={"state": "cancelled", "revision": row.revision + 1})
        if not dry_run:
            if not self.store.save(changed, expected):
                raise ServiceError(409, "stale_revision")
            self.event(actor, row, "task.cancelled", reason)
        return changed

    def inbox(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        view: str,
        mode: str,
        target: UUID | None,
        after: UUID | None,
    ) -> tuple[list[Task], UUID | None]:
        self.schedules.require(actor, org, workspace, project)
        user = self.schedules.forms.authorization.user(actor, org)
        manager = "schedule.manage" in self.schedules.forms.permissions(
            actor, org, workspace, project
        )
        assignment: str | None = None
        personal: UUID | None = user.id
        if mode == "project":
            if not manager:
                raise ServiceError(403, "access_denied")
            personal = None
        elif mode in {"team", "department"}:
            if target is None:
                raise ServiceError(422, "assignment_target_required")
            group = self.schedules.forms.groups.get(org, workspace, target)
            if group.kind.value != mode or not group.active:
                raise ServiceError(404, "not_found")
            if not manager and not any(
                m.group_id == target
                for m in self.schedules.forms.groups.store.memberships(org, workspace, user.id)
            ):
                raise ServiceError(403, "access_denied")
            assignment = mode + ":" + str(target)
            personal = None if manager else user.id
        now = datetime.now(UTC)
        zone = self.schedules.forms.workspaces.organizations.active(org).settings.timezone
        local = now.astimezone(ZoneInfo(zone))
        today = datetime.combine(local.date(), datetime.min.time(), ZoneInfo(zone)).astimezone(UTC)
        tomorrow = datetime.combine(
            local.date() + timedelta(days=1), datetime.min.time(), ZoneInfo(zone)
        ).astimezone(UTC)
        rows = self.store.list_tasks(
            org,
            workspace,
            project,
            personal,
            assignment,
            view,
            now if view == "overdue" else today,
            tomorrow,
            after,
        )
        return [self.public(actor, row) for row in rows[:100]], rows[99].id if len(
            rows
        ) > 100 else None

    def generate_reminders(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        project: UUID | None,
        after: UUID | None,
    ) -> tuple[int, UUID | None]:
        self.schedules.require(actor, org, workspace, project, True)
        now = datetime.now(UTC)
        rows = self.store.reminder_candidates(
            org, workspace, project, now + timedelta(days=30), after
        )
        count = 0
        for task in rows[:100]:
            for offset in task.reminder_offsets:
                due = task.due_at + timedelta(seconds=offset)
                if due <= now:
                    reminder = Reminder(
                        id=uuid7(),
                        organization_id=org,
                        workspace_id=workspace,
                        task_id=task.id,
                        offset_seconds=offset,
                        scheduled_at=due,
                        created_at=now,
                    )
                    if self.store.add_reminder(reminder):
                        count += 1
                        self.event(
                            actor,
                            task,
                            "task.reminder.created",
                            event_id=reminder.id,
                            reminder_id=reminder.id,
                            scheduled_at=due,
                            include_submission=False,
                        )
        return count, rows[99].id if len(rows) > 100 else None
