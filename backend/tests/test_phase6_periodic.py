from datetime import UTC, datetime, timedelta, tzinfo
from uuid import UUID, uuid7

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from operations.composition import compose
from operations.contracts import ServiceError
from operations.modules.audit.infrastructure.persistence import AuditRow
from operations.modules.automation.application import service as automation_module
from operations.modules.automation.application.contracts import (
    MetadataAction,
    Rule,
    RuleDefinition,
    TaskAction,
)
from operations.modules.automation.application.events import (
    DeliveryMessage,
    EventContext,
    OperationalEvent,
)
from operations.modules.automation.application.timers import first_slot
from operations.modules.automation.domain.reliability import delivery_id
from operations.modules.automation.infrastructure.persistence import EventRow, RunRow
from operations.modules.automation.infrastructure.timers import TimerOccurrenceRow
from operations.modules.iam.infrastructure.persistence import GrantRow
from operations.modules.identity.application.contracts import Principal, RequestContext
from operations.modules.identity.infrastructure.persistence import UserRow
from operations.modules.tasks.infrastructure.persistence import DeadlineRow, TaskRow
from operations.worker import process_automation
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from test_oidc import signing_key as signing_key
from test_phase1_api import Api
from test_phase1_api import api as api
from test_phase2_api import project
from test_phase4_api import activate, generate, schedule_setup

pytestmark = pytest.mark.integration


def actor_for(api: Api, org: UUID) -> RequestContext:
    user = api.session.scalar(select(UserRow).where(UserRow.organization_id == org))
    assert user
    return RequestContext(Principal(user.issuer, user.subject), uuid7(), uuid7())


def task_fixture(api: Api) -> tuple[RequestContext, UUID, UUID, TaskRow]:
    route, schedule, _ = schedule_setup(api)
    activate(api, route, schedule)
    generate(api, route, schedule)
    org, workspace = UUID(route.split("/")[4]), UUID(route.split("/")[6])
    task = api.session.scalar(select(TaskRow).where(TaskRow.organization_id == org))
    assert task
    return actor_for(api, org), org, workspace, task


def timer_fixture(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    seconds: int = 60,
) -> tuple[RequestContext, UUID, UUID, Rule, datetime]:
    org = api.organization()
    workspace = api.workspace(org)
    project_id = UUID(project(api, org, workspace))
    actor = actor_for(api, org)
    service = compose(api.session).automation
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=4)
    rule = service.create(
        actor,
        org,
        workspace,
        project_id,
        "Periodic metadata",
        RuleDefinition(
            trigger="scheduled.timer",
            timer_start=start,
            timer_seconds=seconds,
            actions=[MetadataAction(kind="set_metadata", description="Timer completed")],
        ),
    )
    preview = service.activate(actor, org, workspace, rule.id, 1, 1, True, None)

    class ActivationClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> ActivationClock:
            return cls.fromtimestamp((start + timedelta(seconds=30)).timestamp(), UTC)

    with monkeypatch.context() as patch:
        patch.setattr(automation_module, "datetime", ActivationClock)
        service.activate(actor, org, workspace, rule.id, 1, 1, False, preview.content_sha256)
    return actor, org, workspace, rule, start


def test_deadline_boundary_preview_duplicates_and_task_state_are_preserved(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    tasks = compose(api.session).tasks
    assert tasks.generate_deadlines(actor, org, workspace, None, now=task.due_at).candidates == 1
    assert not api.session.scalar(select(func.count()).select_from(DeadlineRow))
    due = tasks.generate_deadlines(actor, org, workspace, None, dry_run=False, now=task.due_at)
    assert due.created == 1
    assert (
        tasks.generate_deadlines(
            actor, org, workspace, None, dry_run=False, now=task.due_at
        ).created
        == 0
    )
    late = tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    assert late.created == 1 and late.cursor is None
    assert tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 0
    api.session.refresh(task)
    assert task.state == "open" and task.revision == 1
    marks = api.session.scalars(select(DeadlineRow).order_by(DeadlineRow.kind)).all()
    assert [mark.kind for mark in marks] == ["due", "overdue"]
    for mark in marks:
        source = compose(api.session).automation.store.event(org, mark.id)
        assert source and source.payload.scheduled_at == task.due_at
        assert source.payload.form_id == task.form_id and source.payload.form_number == 1
        assert source.payload.submission_id is None
    with pytest.raises(ServiceError, match="deadline_timezone_required"):
        tasks.generate_deadlines(actor, org, workspace, None, now=datetime.now())


def test_deadline_tick_rolls_back_audits_outbox_runs_and_marks(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    tasks = compose(api.session).tasks
    with pytest.raises(RuntimeError), api.session.begin_nested():
        assert tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 2
        raise RuntimeError("source transaction rolled back")
    assert not api.session.scalar(select(func.count()).select_from(DeadlineRow))
    assert not api.session.scalar(
        select(func.count()).select_from(EventRow).where(EventRow.type == "task.due")
    )
    assert not api.session.scalar(
        select(func.count()).select_from(AuditRow).where(AuditRow.type == "task.overdue")
    )
    assert tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 2
    with pytest.raises(ServiceError, match="not_found"):
        tasks.generate_deadlines(actor, uuid7(), workspace, None, dry_run=False)
    api.session.execute(
        update(GrantRow).where(GrantRow.organization_id == org).values(revoked=True)
    )
    with pytest.raises(ServiceError, match="access_denied"):
        tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)


def test_private_draft_is_not_deadline_condition_source(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    tasks = compose(api.session).tasks
    claimed = tasks.claim(actor, org, workspace, task.id, 1)
    assert claimed.submission_id
    assert tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 2
    sources = api.session.scalars(
        select(EventRow).where(EventRow.type.in_(["task.due", "task.overdue"]))
    ).all()
    assert len(sources) == 2
    assert all(
        OperationalEvent.model_validate(row.envelope).payload.submission_id is None
        for row in sources
    )


def test_cancelled_task_does_not_receive_retrospective_deadline_events(api: Api) -> None:
    actor, org, workspace, task = task_fixture(api)
    tasks = compose(api.session).tasks
    tasks.cancel(actor, org, workspace, task.id, 1, "cancel test work", False)
    assert tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 0
    assert not api.session.scalar(select(func.count()).select_from(DeadlineRow))


def test_timer_bounded_catchup_only_matches_own_version_and_executes_once(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, org, workspace, rule, start = timer_fixture(api, monkeypatch)
    services = compose(api.session)
    sibling = services.automation.create(
        actor,
        org,
        workspace,
        rule.project_id,
        "Other timer",
        RuleDefinition(
            trigger="scheduled.timer",
            timer_start=start,
            timer_seconds=60,
            actions=[MetadataAction(kind="set_metadata", description="Sibling must not execute")],
        ),
    )
    preview = services.automation.activate(actor, org, workspace, sibling.id, 1, 1, True, None)
    services.automation.activate(
        actor, org, workspace, sibling.id, 1, 1, False, preview.content_sha256
    )
    cutoff = start + timedelta(seconds=60 * 103)
    preview_tick = services.timers.tick(actor, org, workspace, rule.id, now=cutoff)
    assert preview_tick.candidates == 100 and preview_tick.more and preview_tick.created == 0
    version = services.automation.store.version(org, workspace, rule.id, 1)
    assert version and rule.project_id
    assert services.timers.store.last(org, version.id) is None
    first = services.timers.tick(actor, org, workspace, rule.id, False, now=cutoff)
    second = services.timers.tick(actor, org, workspace, rule.id, False, now=cutoff)
    assert first.created == 100 and first.more and second.created == 3 and not second.more
    assert services.timers.tick(actor, org, workspace, rule.id, False, now=cutoff).created == 0
    assert services.timers.store.last(org, version.id) == cutoff
    rows = api.session.scalars(
        select(TimerOccurrenceRow).order_by(TimerOccurrenceRow.scheduled_at)
    ).all()
    assert len(rows) == 103 and rows[0].scheduled_at == start + timedelta(seconds=60)
    source = services.automation.store.event(org, rows[0].id)
    assert source and source.payload.timer_version_id == rows[0].rule_version_id
    runs = services.automation.store.event_runs(org, source.id)
    assert len(runs) == 1 and runs[0].rule_version_id == rows[0].rule_version_id
    other_version = services.automation.store.version(org, workspace, sibling.id, 1)
    assert other_version
    with pytest.raises(DBAPIError), api.session.begin_nested():
        services.automation.store.add_run(
            runs[0].model_copy(update={"id": uuid7(), "rule_version_id": other_version.id})
        )
    for sql in (
        "UPDATE automation_timer_occurrences SET scheduled_at=scheduled_at",
        "DELETE FROM automation_timer_occurrences",
        "TRUNCATE automation_timer_occurrences CASCADE",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(source.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    assert process_automation(api.session, message).state == "completed"
    target = services.projects.require_access(
        actor, org, workspace, rule.project_id, "project.read"
    )
    assert target.context.description == "Timer completed" and target.version == 2
    assert len(services.automation.store.receipts(org, runs[0].id)) == 1


def test_timer_rollback_retirement_and_new_version_do_not_rewrite_progress(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, org, workspace, rule, start = timer_fixture(api, monkeypatch)
    services = compose(api.session)
    with pytest.raises(RuntimeError), api.session.begin_nested():
        assert (
            services.timers.tick(
                actor, org, workspace, rule.id, False, now=start + timedelta(seconds=60)
            ).created
            == 1
        )
        raise RuntimeError("source rollback")
    assert not api.session.scalar(select(func.count()).select_from(TimerOccurrenceRow))
    assert not api.session.scalar(select(func.count()).select_from(RunRow))
    assert (
        services.timers.tick(
            actor, org, workspace, rule.id, False, now=start + timedelta(seconds=60)
        ).created
        == 1
    )
    version = services.automation.store.version(org, workspace, rule.id, 1)
    assert version
    services.automation.retire(actor, org, workspace, rule.id, 2, "stop periodic rule")
    with pytest.raises(ServiceError, match="timer_rule_not_active"):
        services.timers.tick(actor, org, workspace, rule.id, False)
    services.automation.clone(actor, org, workspace, rule.id, 1, 2)
    preview = services.automation.activate(actor, org, workspace, rule.id, 2, 1, True, None)
    current = services.automation.activate(
        actor, org, workspace, rule.id, 2, 1, False, preview.content_sha256
    )
    assert current.activated_at
    # The old cadence's historical slots are not replayed for the newly activated version.
    assert (
        services.timers.tick(
            actor, org, workspace, rule.id, False, now=current.activated_at
        ).created
        == 0
    )
    assert services.timers.store.last(org, version.id) == start + timedelta(seconds=60)


def test_periodic_evidence_is_immutable_and_populated_rollback_refuses(api: Api) -> None:
    actor, org, workspace, _ = task_fixture(api)
    compose(api.session).tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    for sql in (
        "UPDATE task_deadline_events SET kind='due'",
        "DELETE FROM task_deadline_events",
        "TRUNCATE task_deadline_events CASCADE",
    ):
        with pytest.raises(DBAPIError), api.session.begin_nested():
            api.session.execute(text(sql))
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("a39df7b251c0")
    assert revision
    with (
        pytest.raises(DBAPIError),
        api.session.begin_nested(),
        Operations.context(MigrationContext.configure(api.session.connection())),
    ):
        revision.module.downgrade()


def test_timer_fresh_authority_and_wrong_scope_are_denied(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, org, workspace, rule, _ = timer_fixture(api, monkeypatch)
    timers = compose(api.session).timers
    with pytest.raises(ServiceError, match="not_found"):
        timers.tick(actor, uuid7(), workspace, rule.id, False)
    token = api.invitation(org, workspace, "WorkspaceAdmin")
    api.accept(org, token)
    operator = RequestContext(Principal(actor.principal.issuer, "invitee"), uuid7(), uuid7())
    api.session.execute(
        update(GrantRow)
        .where(GrantRow.organization_id == org, GrantRow.role == "OrganizationAdmin")
        .values(revoked=True)
    )
    with pytest.raises(ServiceError, match="access_denied"):
        timers.tick(actor, org, workspace, rule.id, False)
    with pytest.raises(ServiceError, match="access_denied"):
        timers.tick(operator, org, workspace, rule.id, False)
    assert not api.session.scalar(select(func.count()).select_from(TimerOccurrenceRow))


def test_pending_deadline_filter_and_bounded_pages_do_not_starve_new_work(api: Api) -> None:
    from operations.modules.scheduling.application.contracts import (
        Assignment,
        Recurrence,
        ScheduleDefinition,
    )

    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    start = datetime.now(UTC) - timedelta(hours=104)
    assert task.form_id is not None and task.form_number is not None
    schedule = services.scheduling.create(
        actor,
        org,
        workspace,
        None,
        "Paged deadlines",
        ScheduleDefinition(
            form_id=task.form_id,
            form_number=task.form_number,
            recurrence=Recurrence(kind="interval", at=start, interval_seconds=3600),
            assignments=[
                Assignment(kind="user", target_id=services.authorization.user(actor, org).id)
            ],
            due_after_seconds=0,
        ),
    )
    preview = services.scheduling.activate(actor, org, workspace, schedule.id, 1, 1, True, None)
    services.scheduling.activate(
        actor, org, workspace, schedule.id, 1, 1, False, preview.content_sha256
    )
    _, created = services.tasks.materialize(
        actor, org, workspace, schedule.id, start, start + timedelta(hours=102, seconds=1), False
    )
    assert created == 103
    first = services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    assert first.created == 200 and first.cursor
    # Restarting from the first page selects pending work, not the already-marked 100 rows.
    second = services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    assert second.created == 8 and second.cursor is None
    assert (
        services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False).created == 0
    )


def test_due_event_runs_form_task_action_once_without_reading_private_draft(api: Api) -> None:
    from operations.modules.scheduling.application.contracts import Assignment

    actor, org, workspace, task = task_fixture(api)
    services = compose(api.session)
    services.tasks.claim(actor, org, workspace, task.id, 1)
    user = services.authorization.user(actor, org)
    rule = services.automation.create(
        actor,
        org,
        workspace,
        None,
        "Due follow-up",
        RuleDefinition(
            trigger="task.due",
            form_id=task.form_id,
            form_number=task.form_number,
            actions=[
                TaskAction(
                    kind="create_form_task",
                    name="Due follow-up",
                    form_id=task.form_id,
                    form_number=task.form_number,
                    assignments=[Assignment(kind="user", target_id=user.id)],
                )
            ],
        ),
    )
    preview = services.automation.activate(actor, org, workspace, rule.id, 1, 1, True, None)
    services.automation.activate(
        actor, org, workspace, rule.id, 1, 1, False, preview.content_sha256
    )
    services.tasks.generate_deadlines(actor, org, workspace, None, dry_run=False)
    mark = api.session.scalar(select(DeadlineRow).where(DeadlineRow.kind == "due"))
    assert mark
    message = DeliveryMessage(organization_id=org, delivery_id=delivery_id(mark.id, "automation"))
    assert process_automation(api.session, message).state == "completed"
    assert process_automation(api.session, message).state == "completed"
    assert api.session.scalar(select(func.count()).select_from(TaskRow)) == 2
    run = services.automation.store.event_runs(org, mark.id)[0]
    assert len(services.automation.store.receipts(org, run.id)) == 1
    source = services.automation.store.event(org, mark.id)
    assert source and source.payload.submission_id is None


def test_first_timer_slot_ceil_and_exact_boundary_and_event_pins() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert first_slot(start, start - timedelta(seconds=1), 60) == start
    assert first_slot(start, start, 60) == start
    assert first_slot(start, start + timedelta(microseconds=1), 60) == start + timedelta(seconds=60)
    assert first_slot(start, start + timedelta(seconds=60), 60) == start + timedelta(seconds=60)
    with pytest.raises(ValidationError):
        EventContext(scheduled_at=datetime.now())
    with pytest.raises(ValidationError):
        OperationalEvent(
            id=uuid7(),
            type="scheduled.timer",
            occurred_at=start,
            organization_id=uuid7(),
            workspace_id=uuid7(),
            correlation_id=uuid7(),
            aggregate_type="timer",
            aggregate_id=uuid7(),
        )
