from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7
from zoneinfo import ZoneInfo

from operations.contracts import ServiceError
from operations.modules.identity.application.contracts import RequestContext
from operations.modules.scheduling.application.service import SchedulingService
from operations.modules.submissions.application.contracts import Submission
from operations.modules.submissions.application.service import SubmissionService
from operations.modules.tasks.application.contracts import Reminder, Task, TaskStore


class TaskService:
    def __init__(
        self, store: TaskStore, schedules: SchedulingService, submissions: SubmissionService
    ) -> None:
        self.store, self.schedules, self.submissions = store, schedules, submissions

    def event(
        self, actor: RequestContext, row: Task, action: str, reason: str | None = None
    ) -> None:
        self.schedules.event(actor, row.organization_id, row.workspace_id, row.id, action, reason)

    def access(
        self,
        actor: RequestContext,
        org: UUID,
        workspace: UUID,
        identifier: UUID,
        execute: bool = False,
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
                actor, org, workspace, row.project_id, "task.execute", True
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
        draft = self.submissions.create(actor, org, workspace, row.form_id, row.form_number)
        if draft.form_version_id != row.form_version_id:
            raise ServiceError(409, "task_form_version_mismatch")
        changed = row.model_copy(
            update={
                "state": "in_progress",
                "claimant_id": user.id,
                "submission_id": draft.id,
                "revision": row.revision + 1,
            }
        )
        if not self.store.save(changed, expected):
            raise ServiceError(409, "task_claim_conflict")
        self.event(actor, row, "task.claimed")
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
                        self.event(actor, task, "task.reminder.created")
        return count, rows[99].id if len(rows) > 100 else None
