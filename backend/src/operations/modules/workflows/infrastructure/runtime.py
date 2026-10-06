from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
    text,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from operations.modules.workflows.application.contracts import (
    AssignedStep,
    WorkflowAction,
    WorkflowInstance,
    WorkflowNotification,
    WorkflowRevision,
    WorkflowStep,
    WorkflowStepMetadata,
)
from operations.modules.workflows.infrastructure.persistence import WorkflowRow, WorkflowVersionRow
from operations.platform.database import Base


class InstanceRow(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "organization_id",
                "workspace_id",
                "workflow_id",
                "workflow_version_id",
                "workflow_number",
            ],
            [
                "workflow_versions.organization_id",
                "workflow_versions.workspace_id",
                "workflow_versions.workflow_id",
                "workflow_versions.id",
                "workflow_versions.number",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_workflow_instance_scope"
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "submission_id", name="uq_workflow_submission"
        ),
        CheckConstraint(
            "state IN ('active','returned','approved','closed','rejected') "
            "AND revision>0 AND workflow_number>0",
            name="workflow_instance_state",
        ),
        Index(
            "ix_workflow_instance_scope_cursor",
            "organization_id",
            "workspace_id",
            "workflow_id",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    workflow_id: Mapped[UUID]
    workflow_version_id: Mapped[UUID]
    workflow_number: Mapped[int]
    submission_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(20))
    current_node: Mapped[str] = mapped_column(String(60))
    revision: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StepRow(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "instance_id"],
            [
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.id",
            ],
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "instance_id", "id", name="uq_workflow_step_scope"
        ),
        UniqueConstraint("organization_id", "instance_id", "number", name="uq_workflow_step_visit"),
        Index(
            "uq_workflow_open_step",
            "organization_id",
            "workspace_id",
            "instance_id",
            unique=True,
            postgresql_where=text("state='open'"),
        ),
        CheckConstraint(
            "number BETWEEN 1 AND 1000 AND state IN ('open','completed','returned','rejected')",
            name="workflow_step_state",
        ),
        Index(
            "ix_workflow_step_instance", "organization_id", "workspace_id", "instance_id", "number"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    instance_id: Mapped[UUID]
    node_key: Mapped[str] = mapped_column(String(60))
    number: Mapped[int]
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecipientRow(Base):
    __tablename__ = "workflow_recipients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "instance_id", "step_id"],
            [
                "workflow_steps.organization_id",
                "workflow_steps.workspace_id",
                "workflow_steps.instance_id",
                "workflow_steps.id",
            ],
        ),
        ForeignKeyConstraint(["organization_id", "user_id"], ["users.organization_id", "users.id"]),
        UniqueConstraint(
            "organization_id", "step_id", "user_id", name="uq_workflow_step_recipient"
        ),
        UniqueConstraint(
            "organization_id", "step_id", "position", name="uq_workflow_recipient_order"
        ),
        CheckConstraint("position BETWEEN 0 AND 999", name="workflow_recipient_position"),
        Index(
            "ix_workflow_recipient_inbox",
            "organization_id",
            "workspace_id",
            "user_id",
            "instance_id",
            "step_id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    instance_id: Mapped[UUID]
    step_id: Mapped[UUID]
    user_id: Mapped[UUID]
    position: Mapped[int]


class ActionRow(Base):
    __tablename__ = "workflow_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "instance_id", "step_id"],
            [
                "workflow_steps.organization_id",
                "workflow_steps.workspace_id",
                "workflow_steps.instance_id",
                "workflow_steps.id",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "actor_id"], ["users.organization_id", "users.id"]
        ),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_action_key"),
        UniqueConstraint("organization_id", "step_id", "actor_id", name="uq_workflow_action_actor"),
        CheckConstraint(
            "kind IN ('review','approve','return','reject') AND length(reason) BETWEEN 1 AND 2000",
            name="workflow_action_kind",
        ),
        Index("ix_workflow_action_history", "organization_id", "workspace_id", "instance_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    instance_id: Mapped[UUID]
    step_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    idempotency_key: Mapped[UUID]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationRow(Base):
    __tablename__ = "workflow_notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "instance_id"],
            [
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.id",
            ],
        ),
        UniqueConstraint(
            "organization_id",
            "instance_id",
            "node_key",
            "visit",
            name="uq_workflow_notification_visit",
        ),
        CheckConstraint("visit > 0", name="workflow_notification_visit"),
        Index("ix_workflow_notification_cursor", "organization_id", "id"),
        Index("ix_workflow_notification_workspace_cursor", "organization_id", "workspace_id", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    instance_id: Mapped[UUID]
    node_key: Mapped[str] = mapped_column(String(60))
    visit: Mapped[int]
    recipient_ids: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevisionRow(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "source_instance_id"],
            [
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.id",
            ],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "root_submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
            name="fk_workflow_revision_root_owner",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
        ),
        UniqueConstraint(
            "organization_id", "source_instance_id", name="uq_workflow_revision_source"
        ),
        UniqueConstraint(
            "organization_id", "submission_id", name="uq_workflow_revision_submission"
        ),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_revision_key"),
        CheckConstraint(
            "kind IN ('correction','amendment') AND length(reason) BETWEEN 1 AND 2000 "
            "AND submission_id <> root_submission_id",
            name="workflow_revision_kind",
        ),
        Index(
            "ix_workflow_revision_scope",
            "organization_id",
            "workspace_id",
            "root_submission_id",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID]
    workspace_id: Mapped[UUID]
    source_instance_id: Mapped[UUID]
    root_submission_id: Mapped[UUID]
    submission_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    idempotency_key: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def instance_contract(row: InstanceRow) -> WorkflowInstance:
    return WorkflowInstance.model_validate(
        {key: getattr(row, key) for key in WorkflowInstance.model_fields}
    )


def action_contract(row: ActionRow) -> WorkflowAction:
    return WorkflowAction.model_validate(
        {key: getattr(row, key) for key in WorkflowAction.model_fields}
    )


class RuntimeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_revision(self, row: WorkflowRevision) -> None:
        self.session.add(RevisionRow(**row.model_dump()))
        self.session.flush()

    def revision_by_submission(
        self, org: UUID, workspace: UUID, submission: UUID
    ) -> WorkflowRevision | None:
        row = self.session.scalar(
            select(RevisionRow).where(
                RevisionRow.organization_id == org,
                RevisionRow.workspace_id == workspace,
                RevisionRow.submission_id == submission,
            )
        )
        return (
            WorkflowRevision.model_validate(
                {key: getattr(row, key) for key in WorkflowRevision.model_fields}
            )
            if row
            else None
        )

    def revision_by_source(
        self, org: UUID, workspace: UUID, instance: UUID
    ) -> WorkflowRevision | None:
        row = self.session.scalar(
            select(RevisionRow).where(
                RevisionRow.organization_id == org,
                RevisionRow.workspace_id == workspace,
                RevisionRow.source_instance_id == instance,
            )
        )
        return (
            WorkflowRevision.model_validate(
                {key: getattr(row, key) for key in WorkflowRevision.model_fields}
            )
            if row
            else None
        )

    def approved_submission(
        self, org: UUID, workspace: UUID, form: UUID, owner: UUID
    ) -> UUID | None:
        last_action = (
            select(ActionRow.instance_id, func.max(ActionRow.occurred_at).label("last_at"))
            .where(ActionRow.organization_id == org, ActionRow.workspace_id == workspace)
            .group_by(ActionRow.instance_id)
            .subquery()
        )
        return self.session.scalar(
            select(InstanceRow.submission_id)
            .join(WorkflowVersionRow, WorkflowVersionRow.id == InstanceRow.workflow_version_id)
            .join(last_action, last_action.c.instance_id == InstanceRow.id)
            .where(
                InstanceRow.organization_id == org,
                InstanceRow.workspace_id == workspace,
                InstanceRow.owner_id == owner,
                InstanceRow.state == "approved",
                WorkflowVersionRow.definition["form_id"].astext == str(form),
            )
            .order_by(last_action.c.last_at.desc(), InstanceRow.id.desc())
            .limit(1)
        )

    def add_instance(self, row: WorkflowInstance) -> None:
        self.session.add(InstanceRow(**row.model_dump()))
        self.session.flush()

    def instance(
        self, org: UUID, workspace: UUID, identifier: UUID, lock: bool = False
    ) -> WorkflowInstance | None:
        query = select(InstanceRow).where(
            InstanceRow.organization_id == org,
            InstanceRow.workspace_id == workspace,
            InstanceRow.id == identifier,
        )
        row = self.session.scalar(query.with_for_update() if lock else query)
        return instance_contract(row) if row else None

    def by_submission(
        self, org: UUID, workspace: UUID, submission: UUID
    ) -> WorkflowInstance | None:
        row = self.session.scalar(
            select(InstanceRow).where(
                InstanceRow.organization_id == org,
                InstanceRow.workspace_id == workspace,
                InstanceRow.submission_id == submission,
            )
        )
        return instance_contract(row) if row else None

    def save_instance(self, row: WorkflowInstance, expected: int) -> bool:
        identifier = self.session.scalar(
            update(InstanceRow)
            .where(
                InstanceRow.organization_id == row.organization_id,
                InstanceRow.workspace_id == row.workspace_id,
                InstanceRow.id == row.id,
                InstanceRow.revision == expected,
            )
            .values(state=row.state, current_node=row.current_node, revision=row.revision)
            .returning(InstanceRow.id)
        )
        self.session.flush()
        return identifier is not None

    def add_step(self, row: WorkflowStep) -> None:
        self.session.add(StepRow(**row.model_dump(exclude={"recipient_ids"})))
        self.session.flush()
        for position, user in enumerate(row.recipient_ids):
            self.session.add(
                RecipientRow(
                    id=uuid7(),
                    organization_id=row.organization_id,
                    workspace_id=row.workspace_id,
                    instance_id=row.instance_id,
                    step_id=row.id,
                    user_id=user,
                    position=position,
                )
            )
        self.session.flush()

    def history_steps(
        self, org: UUID, workspace: UUID, instance: UUID, after: int | None = None
    ) -> list[WorkflowStep]:
        rows = list(
            self.session.scalars(
                select(StepRow)
                .where(
                    StepRow.organization_id == org,
                    StepRow.workspace_id == workspace,
                    StepRow.instance_id == instance,
                    StepRow.number > (after or 0),
                )
                .order_by(StepRow.number)
                .limit(21)
            )
        )
        recipients = list(
            self.session.scalars(
                select(RecipientRow)
                .where(
                    RecipientRow.organization_id == org,
                    RecipientRow.workspace_id == workspace,
                    RecipientRow.instance_id == instance,
                    RecipientRow.step_id.in_([row.id for row in rows]),
                )
                .order_by(RecipientRow.position)
            )
        )
        return [
            WorkflowStep.model_validate(
                {
                    **{
                        key: getattr(row, key)
                        for key in WorkflowStep.model_fields
                        if key != "recipient_ids"
                    },
                    "recipient_ids": [
                        recipient.user_id for recipient in recipients if recipient.step_id == row.id
                    ],
                }
            )
            for row in rows
        ]

    def current_step(
        self, org: UUID, workspace: UUID, instance: UUID, node: str
    ) -> WorkflowStep | None:
        row = self.session.scalar(
            select(StepRow)
            .where(
                StepRow.organization_id == org,
                StepRow.workspace_id == workspace,
                StepRow.instance_id == instance,
                StepRow.node_key == node,
                StepRow.state == "open",
            )
            .order_by(StepRow.number.desc())
            .limit(1)
        )
        if row is None:
            return None
        users = list(
            self.session.scalars(
                select(RecipientRow.user_id)
                .where(
                    RecipientRow.organization_id == org,
                    RecipientRow.workspace_id == workspace,
                    RecipientRow.step_id == row.id,
                )
                .order_by(RecipientRow.position)
            )
        )
        return WorkflowStep.model_validate(
            {
                **{key: getattr(row, key) for key in WorkflowStepMetadata.model_fields},
                "recipient_ids": users,
            }
        )

    def participant_steps(
        self, org: UUID, workspace: UUID, instance: UUID, user: UUID
    ) -> list[AssignedStep]:
        query = (
            select(StepRow)
            .join(RecipientRow, RecipientRow.step_id == StepRow.id)
            .where(
                StepRow.organization_id == org,
                StepRow.workspace_id == workspace,
                StepRow.instance_id == instance,
                RecipientRow.organization_id == org,
                RecipientRow.workspace_id == workspace,
                RecipientRow.user_id == user,
            )
            .order_by(StepRow.number)
            .limit(1001)
        )
        return [
            AssignedStep.model_validate(
                {
                    **{key: getattr(row, key) for key in WorkflowStepMetadata.model_fields},
                    "recipient_id": user,
                }
            )
            for row in self.session.scalars(query)
        ]

    def step_count(self, org: UUID, workspace: UUID, instance: UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(StepRow)
                .where(
                    StepRow.organization_id == org,
                    StepRow.workspace_id == workspace,
                    StepRow.instance_id == instance,
                )
            )
            or 0
        )

    def completed_approval(
        self, org: UUID, workspace: UUID, instance: UUID, node_keys: set[str]
    ) -> bool:
        return (
            self.session.scalar(
                select(StepRow.id)
                .where(
                    StepRow.organization_id == org,
                    StepRow.workspace_id == workspace,
                    StepRow.instance_id == instance,
                    StepRow.node_key.in_(node_keys),
                    StepRow.state == "completed",
                )
                .limit(1)
            )
            is not None
        )

    def save_step(self, row: WorkflowStep) -> None:
        identifier = self.session.scalar(
            update(StepRow)
            .where(
                StepRow.organization_id == row.organization_id,
                StepRow.workspace_id == row.workspace_id,
                StepRow.id == row.id,
                StepRow.state == "open",
            )
            .values(state=row.state)
            .returning(StepRow.id)
        )
        if identifier is None:
            raise ValueError("workflow_step_conflict")
        self.session.flush()

    def add_action(self, row: WorkflowAction) -> None:
        self.session.add(ActionRow(**row.model_dump()))
        self.session.flush()

    def actions(
        self, org: UUID, workspace: UUID, instance: UUID, after: UUID | None = None
    ) -> list[WorkflowAction]:
        return [
            action_contract(row)
            for row in self.session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.organization_id == org,
                    ActionRow.workspace_id == workspace,
                    ActionRow.instance_id == instance,
                    ActionRow.id > after if after else true(),
                )
                .order_by(ActionRow.id)
                .limit(101)
            )
        ]

    def actions_for_step(
        self, org: UUID, workspace: UUID, instance: UUID, step: UUID
    ) -> list[WorkflowAction]:
        return [
            action_contract(row)
            for row in self.session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.organization_id == org,
                    ActionRow.workspace_id == workspace,
                    ActionRow.instance_id == instance,
                    ActionRow.step_id == step,
                )
                .order_by(ActionRow.id)
                .limit(1001)
            )
        ]

    def action_by_key(self, org: UUID, key: UUID) -> WorkflowAction | None:
        row = self.session.scalar(
            select(ActionRow).where(
                ActionRow.organization_id == org, ActionRow.idempotency_key == key
            )
        )
        return action_contract(row) if row else None

    def inbox(
        self, org: UUID, workspace: UUID, user: UUID, project: UUID | None, after: UUID | None
    ) -> list[WorkflowInstance]:
        query = (
            select(InstanceRow)
            .join(
                WorkflowRow,
                (WorkflowRow.id == InstanceRow.workflow_id) & (WorkflowRow.organization_id == org),
            )
            .where(
                InstanceRow.organization_id == org,
                InstanceRow.workspace_id == workspace,
                InstanceRow.state == "active",
                WorkflowRow.project_id == project,
            )
        )
        assigned = (
            select(RecipientRow.instance_id)
            .join(StepRow, StepRow.id == RecipientRow.step_id)
            .where(
                RecipientRow.organization_id == org,
                RecipientRow.workspace_id == workspace,
                RecipientRow.user_id == user,
                StepRow.state == "open",
            )
        )
        query = query.where(InstanceRow.id.in_(assigned))
        if after:
            query = query.where(InstanceRow.id > after)
        return [
            instance_contract(row)
            for row in self.session.scalars(query.order_by(InstanceRow.id).limit(101))
        ]

    def notify(self, row: WorkflowNotification) -> None:
        values = row.model_dump()
        values["recipient_ids"] = [str(user) for user in row.recipient_ids]
        self.session.add(NotificationRow(**values))
        self.session.flush()

    def notification_intents(
        self, org: UUID, workspace: UUID, after: UUID | None
    ) -> list[WorkflowNotification]:
        query = select(NotificationRow).where(
            NotificationRow.organization_id == org, NotificationRow.workspace_id == workspace
        )
        if after:
            query = query.where(NotificationRow.id > after)
        return [
            WorkflowNotification.model_validate(
                {key: getattr(row, key) for key in WorkflowNotification.model_fields}
            )
            for row in self.session.scalars(query.order_by(NotificationRow.id).limit(101))
        ]

    def notification(
        self, org: UUID, workspace: UUID, identifier: UUID
    ) -> WorkflowNotification | None:
        row = self.session.scalar(
            select(NotificationRow).where(
                NotificationRow.organization_id == org,
                NotificationRow.workspace_id == workspace,
                NotificationRow.id == identifier,
            )
        )
        return (
            WorkflowNotification.model_validate(
                {key: getattr(row, key) for key in WorkflowNotification.model_fields}
            )
            if row
            else None
        )
