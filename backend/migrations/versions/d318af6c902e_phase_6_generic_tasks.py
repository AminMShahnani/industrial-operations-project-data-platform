"""Generic work acknowledgements; preserve form tasks and retained history."""

import sqlalchemy as sa
from alembic import op

revision = "d318af6c902e"
down_revision = "ba6e379cc281"
branch_labels = None
depends_on = None

PIN_COLUMNS = (
    "schedule_id",
    "schedule_version_id",
    "schedule_number",
    "form_id",
    "form_version_id",
    "form_number",
)

KIND_CHECK = """
(kind='form' AND origin_id IS NULL AND schedule_id IS NOT NULL
AND schedule_version_id IS NOT NULL AND schedule_number IS NOT NULL
AND form_id IS NOT NULL AND form_version_id IS NOT NULL AND form_number IS NOT NULL
AND completed_at IS NULL AND state<>'completed') OR (kind='generic'
AND origin_id IS NOT NULL AND schedule_id IS NULL AND schedule_version_id IS NULL
AND schedule_number IS NULL AND form_id IS NULL AND form_version_id IS NULL
AND form_number IS NULL AND submission_id IS NULL
AND state IN ('open','in_progress','completed','cancelled')
AND ((state='completed' AND completed_at IS NOT NULL AND completed_at>=occurs_at)
OR (state<>'completed' AND completed_at IS NULL)))
"""
STATE_CHECK = (
    "revision > 0 AND due_at >= occurs_at AND state IN ('open','in_progress',"
    "'submitted','awaiting_review','returned','approved','cancelled','superseded','completed')"
)
OLD_CLAIM = """(state IN ('open','superseded') AND claimant_id IS NULL AND submission_id IS NULL)
OR state='cancelled' OR (state IN ('in_progress','submitted','awaiting_review',
'returned','approved') AND claimant_id IS NOT NULL AND submission_id IS NOT NULL)"""
CLAIM_CHECK = """(state IN ('open','superseded') AND claimant_id IS NULL AND submission_id IS NULL)
OR state='cancelled' OR (state IN ('in_progress','submitted','awaiting_review',
'returned','approved') AND claimant_id IS NOT NULL AND submission_id IS NOT NULL AND kind='form')
OR (kind='generic' AND state IN ('in_progress','completed')
AND claimant_id IS NOT NULL AND submission_id IS NULL)"""

GENERIC_GUARD = """
      IF TG_TABLE_NAME='task_occurrences' AND TG_OP IN ('INSERT','UPDATE') THEN
        IF TG_OP='UPDATE' AND NEW.kind IS DISTINCT FROM OLD.kind THEN
          RAISE EXCEPTION 'Immutable task kind' USING ERRCODE='55000';
        END IF;
        IF NEW.kind='generic' THEN
          IF TG_OP='INSERT' THEN
            IF NEW.state<>'open' OR NEW.revision<>1 OR NEW.claimant_id IS NOT NULL THEN
              RAISE EXCEPTION 'Generic task must start open' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.revision<>OLD.revision+1 OR
            (to_jsonb(NEW)-'revision'-'state'-'claimant_id'-'completed_at') IS DISTINCT FROM
            (to_jsonb(OLD)-'revision'-'state'-'claimant_id'-'completed_at')
            OR NOT ((OLD.state='open' AND NEW.state IN ('in_progress','cancelled'))
              OR (OLD.state='in_progress' AND NEW.state IN ('completed','cancelled')))
            OR (OLD.claimant_id IS NOT NULL AND NEW.claimant_id IS DISTINCT FROM OLD.claimant_id)
          THEN RAISE EXCEPTION 'Immutable generic task history/claim' USING ERRCODE='55000'; END IF;
          IF NEW.claimant_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM task_recipients
            WHERE task_id=NEW.id AND organization_id=NEW.organization_id
            AND user_id=NEW.claimant_id)
          THEN RAISE EXCEPTION 'Claimant not assigned' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END IF;
      END IF;
"""


def task_triggers(function: str) -> None:
    for name, event, level in (
        ("protect_task_occurrences_changes", "UPDATE OR DELETE", "ROW"),
        ("protect_task_occurrences_truncate", "TRUNCATE", "STATEMENT"),
        ("protect_task_exact_insert", "INSERT", "ROW"),
    ):
        op.execute(f"DROP TRIGGER {name} ON task_occurrences")
        op.execute(
            f"CREATE TRIGGER {name} BEFORE {event} ON task_occurrences FOR EACH {level} "
            f"EXECUTE FUNCTION {function}()"
        )


def upgrade() -> None:
    op.add_column(
        "task_occurrences", sa.Column("kind", sa.String(10), nullable=False, server_default="form")
    )
    op.add_column("task_occurrences", sa.Column("origin_id", sa.Uuid(), nullable=True))
    op.add_column(
        "task_occurrences", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    for column in PIN_COLUMNS:
        op.alter_column("task_occurrences", column, nullable=True)
    op.create_foreign_key(
        "fk_task_occurrences_organization_id_workspaces",
        "task_occurrences",
        "workspaces",
        ["organization_id", "workspace_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_task_generic_origin",
        "task_occurrences",
        ["organization_id", "origin_id", "assignment_key"],
    )
    for name, condition in (("task_state", STATE_CHECK), ("task_claim", CLAIM_CHECK)):
        op.drop_constraint(op.f("ck_task_occurrences_" + name), "task_occurrences", type_="check")
        op.create_check_constraint(
            op.f("ck_task_occurrences_" + name), "task_occurrences", condition
        )
    op.create_check_constraint(
        op.f("ck_task_occurrences_task_kind"), "task_occurrences", KIND_CHECK
    )
    op.execute(
        FORM_GUARD.replace("protect_phase4_record()", "protect_phase6_task_record()").replace(
            "    BEGIN", "    BEGIN" + GENERIC_GUARD, 1
        )
    )
    task_triggers("protect_phase6_task_record")


def downgrade() -> None:
    # Serialize the preflight with writes before changing any guard or column.
    op.execute("LOCK TABLE task_occurrences IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM task_occurrences WHERE kind='generic') THEN
        RAISE EXCEPTION 'Retained generic tasks prevent rollback; restore a verified backup'
        USING ERRCODE='55000';
      END IF;
    END $$;""")
    task_triggers("protect_phase4_record")
    op.execute("DROP FUNCTION protect_phase6_task_record()")
    op.drop_constraint(op.f("ck_task_occurrences_task_kind"), "task_occurrences", type_="check")
    for name, condition in (
        ("task_state", STATE_CHECK.replace(",'completed'", "")),
        ("task_claim", OLD_CLAIM),
    ):
        op.drop_constraint(op.f("ck_task_occurrences_" + name), "task_occurrences", type_="check")
        op.create_check_constraint(
            op.f("ck_task_occurrences_" + name), "task_occurrences", condition
        )
    op.drop_constraint("uq_task_generic_origin", "task_occurrences", type_="unique")
    op.drop_constraint(
        "fk_task_occurrences_organization_id_workspaces", "task_occurrences", type_="foreignkey"
    )
    for column in PIN_COLUMNS:
        op.alter_column("task_occurrences", column, nullable=False)
    for column in ("completed_at", "origin_id", "kind"):
        op.drop_column("task_occurrences", column)


# Frozen Phase 5 form-task guard; do not import evolving application models.
FORM_GUARD = """
    CREATE OR REPLACE FUNCTION protect_phase4_record() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP IN ('DELETE','TRUNCATE') THEN
        RAISE EXCEPTION 'Phase 4 history is retained' USING ERRCODE='55000';
      END IF;
      IF TG_OP='INSERT' AND TG_TABLE_NAME='task_occurrences' THEN
        IF NOT EXISTS (
          SELECT 1 FROM schedules s JOIN schedule_versions v
          ON v.schedule_id=s.id AND v.organization_id=s.organization_id
          WHERE s.organization_id=NEW.organization_id AND s.workspace_id=NEW.workspace_id
          AND s.id=NEW.schedule_id AND v.id=NEW.schedule_version_id
          AND s.project_id IS NOT DISTINCT FROM NEW.project_id
          AND v.form_version_id=NEW.form_version_id
          AND v.definition->>'form_id'=NEW.form_id::text
          AND (v.definition->>'form_number')::integer=NEW.form_number
        ) THEN RAISE EXCEPTION 'Task exact scope/version mismatch' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END IF;
      IF TG_TABLE_NAME IN ('schedule_shifts','schedule_triggers','project_milestones',
        'task_recipients','task_reminders') THEN
        RAISE EXCEPTION 'Immutable Phase 4 snapshot' USING ERRCODE='55000';
      END IF;
      IF NEW.revision<>OLD.revision+1 THEN
        RAISE EXCEPTION 'Revision must increment' USING ERRCODE='55000';
      END IF;
      IF TG_TABLE_NAME='schedules' THEN
        IF (to_jsonb(NEW)-'revision'-'active_number') IS DISTINCT FROM
           (to_jsonb(OLD)-'revision'-'active_number') THEN
          RAISE EXCEPTION 'Immutable schedule identity' USING ERRCODE='55000';
        END IF;
      ELSIF TG_TABLE_NAME='schedule_versions' THEN
        IF (to_jsonb(NEW)-'revision'-'definition'-'state'-'form_version_id'
            -'activated_at'-'content_sha256')
          IS DISTINCT FROM
          (to_jsonb(OLD)-'revision'-'definition'-'state'-'form_version_id'
           -'activated_at'-'content_sha256')
          THEN RAISE EXCEPTION 'Immutable version identity' USING ERRCODE='55000'; END IF;
        IF OLD.state='draft' THEN
          IF NEW.state NOT IN ('draft','active') THEN
            RAISE EXCEPTION 'Invalid activation' USING ERRCODE='55000'; END IF;
        ELSE
          IF (to_jsonb(NEW)-'revision'-'state') IS DISTINCT FROM (to_jsonb(OLD)-'revision'-'state')
          OR NOT ((OLD.state='active' AND NEW.state IN ('paused','retired'))
             OR (OLD.state='paused' AND NEW.state IN ('active','retired')))
          THEN RAISE EXCEPTION 'Immutable active schedule' USING ERRCODE='55000'; END IF;
        END IF;
      ELSIF TG_TABLE_NAME='task_occurrences' THEN
        IF (to_jsonb(NEW)-'revision'-'state'-'claimant_id'-'submission_id') IS DISTINCT FROM
          (to_jsonb(OLD)-'revision'-'state'-'claimant_id'-'submission_id')
        OR NOT ((OLD.state='open' AND NEW.state IN ('in_progress','cancelled','superseded'))
             OR (OLD.state='in_progress' AND NEW.state IN ('submitted','cancelled'))
             OR (OLD.state IN ('submitted','awaiting_review','returned','approved')
               AND NEW.state IN ('submitted','awaiting_review','returned','approved')))
        OR (OLD.claimant_id IS NOT NULL AND
           (NEW.claimant_id IS DISTINCT FROM OLD.claimant_id
            OR NEW.submission_id IS DISTINCT FROM OLD.submission_id))
        THEN RAISE EXCEPTION 'Immutable task history/claim' USING ERRCODE='55000'; END IF;
        IF OLD.state IN ('submitted','awaiting_review','returned','approved') THEN
          IF NOT EXISTS(
            SELECT 1 FROM (
              SELECT wi.state FROM workflow_instances wi
              LEFT JOIN workflow_revisions r ON r.submission_id=wi.submission_id
                AND r.organization_id=wi.organization_id AND r.workspace_id=wi.workspace_id
              WHERE wi.organization_id=NEW.organization_id AND wi.workspace_id=NEW.workspace_id
                AND wi.owner_id=NEW.claimant_id
                AND (wi.submission_id=NEW.submission_id OR r.root_submission_id=NEW.submission_id)
              ORDER BY wi.id DESC LIMIT 1
            ) latest WHERE NEW.state = CASE latest.state
              WHEN 'active' THEN 'awaiting_review' WHEN 'approved' THEN 'approved'
              WHEN 'closed' THEN 'submitted' ELSE 'returned' END
          ) THEN RAISE EXCEPTION 'Task transition requires authoritative workflow state'
            USING ERRCODE='55000'; END IF;
        END IF;
        IF NEW.claimant_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM task_recipients
          WHERE task_id=NEW.id AND organization_id=NEW.organization_id AND user_id=NEW.claimant_id)
          THEN RAISE EXCEPTION 'Claimant not assigned' USING ERRCODE='23514'; END IF;
        IF NEW.state='submitted' AND NOT EXISTS (SELECT 1 FROM submissions
          WHERE organization_id=NEW.organization_id AND id=NEW.submission_id
          AND state='submitted' AND form_version_id=NEW.form_version_id)
          THEN RAISE EXCEPTION 'Task requires exact submitted snapshot'
          USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
