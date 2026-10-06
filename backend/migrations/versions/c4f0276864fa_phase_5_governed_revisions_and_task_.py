"""phase 5 governed revisions and task handoff"""

import sqlalchemy as sa
from alembic import op

revision = "c4f0276864fa"
down_revision = "1223fa111b4c"
branch_labels = None
depends_on = None


OLD_RUNTIME_GUARD = """
    CREATE OR REPLACE FUNCTION protect_workflow_runtime() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE node jsonb; votes integer; recipients integer; required_votes integer;
    BEGIN
      IF TG_OP IN ('DELETE','TRUNCATE') THEN
        RAISE EXCEPTION 'Workflow history cannot be deleted' USING ERRCODE='55000';
      END IF;
      IF TG_OP='UPDATE' THEN
        IF TG_TABLE_NAME='workflow_instances' THEN
          IF OLD.state <> 'active' OR NEW.revision <> OLD.revision+1 OR
            (to_jsonb(NEW)-ARRAY['state','current_node','revision']) IS DISTINCT FROM
            (to_jsonb(OLD)-ARRAY['state','current_node','revision']) THEN
            RAISE EXCEPTION 'Invalid workflow instance transition' USING ERRCODE='55000';
          END IF;
        ELSIF TG_TABLE_NAME='workflow_steps' THEN
          IF OLD.state <> 'open' OR NEW.state='open' OR
            (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state') THEN
            RAISE EXCEPTION 'Workflow visit is immutable' USING ERRCODE='55000';
          END IF;
          IF NEW.state='completed' THEN
            SELECT n INTO node FROM workflow_instances i
              JOIN workflow_versions v ON v.id=i.workflow_version_id,
              LATERAL jsonb_array_elements(v.definition->'nodes') n
              WHERE i.id=NEW.instance_id AND n->>'key'=NEW.node_key;
            SELECT count(*) INTO recipients FROM workflow_recipients r WHERE r.step_id=NEW.id;
            SELECT count(*) INTO votes FROM workflow_actions a WHERE a.step_id=NEW.id
              AND a.kind=CASE WHEN node->>'kind'='approval' THEN 'approve' ELSE 'review' END;
            required_votes := CASE node->'policy'->>'mode'
              WHEN 'one' THEN 1 WHEN 'quorum' THEN (node->'policy'->>'quorum')::integer
              ELSE recipients END;
            IF required_votes IS NULL OR required_votes<1 OR votes<required_votes THEN
              RAISE EXCEPTION 'Workflow completion policy not satisfied' USING ERRCODE='55000';
            END IF;
          ELSE
            IF NOT EXISTS(SELECT 1 FROM workflow_actions a WHERE a.step_id=NEW.id
              AND a.kind=CASE WHEN NEW.state='returned' THEN 'return' ELSE 'reject' END) THEN
              RAISE EXCEPTION 'Workflow decision evidence required' USING ERRCODE='55000';
            END IF;
          END IF;
        ELSE
          RAISE EXCEPTION 'Workflow evidence is immutable' USING ERRCODE='55000';
        END IF;
      END IF;
      IF TG_OP='INSERT' AND TG_TABLE_NAME='workflow_instances' THEN
        IF NOT EXISTS(SELECT 1 FROM submissions s JOIN workflow_versions v
          ON v.id=NEW.workflow_version_id WHERE s.id=NEW.submission_id
          AND s.organization_id=NEW.organization_id AND s.workspace_id=NEW.workspace_id
          AND s.owner_id=NEW.owner_id AND s.state='submitted'
          AND s.form_version_id=v.form_version_id AND v.state='active') THEN
          RAISE EXCEPTION 'Submitted workflow snapshot required' USING ERRCODE='55000';
        END IF;
      END IF;
      IF TG_OP='INSERT' AND TG_TABLE_NAME='workflow_actions' THEN
        SELECT n INTO node FROM workflow_steps st
          JOIN workflow_instances i ON i.id=st.instance_id
          JOIN workflow_versions v ON v.id=i.workflow_version_id,
          LATERAL jsonb_array_elements(v.definition->'nodes') n
          WHERE st.id=NEW.step_id AND st.state='open' AND i.state='active'
          AND i.current_node=st.node_key AND n->>'key'=st.node_key;
        IF node IS NULL OR NOT EXISTS(SELECT 1 FROM workflow_recipients r
          WHERE r.step_id=NEW.step_id AND r.user_id=NEW.actor_id) THEN
          RAISE EXCEPTION 'Open assigned workflow step required' USING ERRCODE='55000';
        END IF;
        IF NEW.kind IN ('approve','review') AND NEW.kind <> (CASE
          WHEN node->>'kind'='approval' THEN 'approve' ELSE 'review' END) THEN
          RAISE EXCEPTION 'Wrong workflow action kind' USING ERRCODE='55000';
        END IF;
        IF NEW.kind='approve' AND EXISTS(SELECT 1 FROM workflow_instances i
          WHERE i.id=NEW.instance_id AND i.owner_id=NEW.actor_id) THEN
          RAISE EXCEPTION 'Independent approval required' USING ERRCODE='55000';
        END IF;
        IF NEW.kind IN ('approve','review') AND node->'policy'->>'mode'='sequential' THEN
          SELECT count(*) INTO votes FROM workflow_actions a WHERE a.step_id=NEW.step_id;
          IF NOT EXISTS(SELECT 1 FROM workflow_recipients r WHERE r.step_id=NEW.step_id
            AND r.user_id=NEW.actor_id AND r.position=votes) THEN
            RAISE EXCEPTION 'Sequential approval order required' USING ERRCODE='55000';
          END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
NEW_RUNTIME_GUARD = """
    CREATE OR REPLACE FUNCTION protect_workflow_runtime() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE node jsonb; votes integer; recipients integer; required_votes integer;
    BEGIN
      IF TG_OP IN ('DELETE','TRUNCATE') THEN
        RAISE EXCEPTION 'Workflow history cannot be deleted' USING ERRCODE='55000';
      END IF;
      IF TG_OP='UPDATE' THEN
        IF TG_TABLE_NAME='workflow_instances' THEN
          IF OLD.state <> 'active' OR NEW.revision <> OLD.revision+1 OR
            (to_jsonb(NEW)-ARRAY['state','current_node','revision']) IS DISTINCT FROM
            (to_jsonb(OLD)-ARRAY['state','current_node','revision']) THEN
            RAISE EXCEPTION 'Invalid workflow instance transition' USING ERRCODE='55000';
          END IF;
        ELSIF TG_TABLE_NAME='workflow_steps' THEN
          IF OLD.state <> 'open' OR NEW.state='open' OR
            (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state') THEN
            RAISE EXCEPTION 'Workflow visit is immutable' USING ERRCODE='55000';
          END IF;
          IF NEW.state='completed' THEN
            SELECT n INTO node FROM workflow_instances i
              JOIN workflow_versions v ON v.id=i.workflow_version_id,
              LATERAL jsonb_array_elements(v.definition->'nodes') n
              WHERE i.id=NEW.instance_id AND n->>'key'=NEW.node_key;
            SELECT count(*) INTO recipients FROM workflow_recipients r WHERE r.step_id=NEW.id;
            SELECT count(*) INTO votes FROM workflow_actions a WHERE a.step_id=NEW.id
              AND a.kind=CASE WHEN node->>'kind'='approval' THEN 'approve' ELSE 'review' END;
            required_votes := CASE node->'policy'->>'mode'
              WHEN 'one' THEN 1 WHEN 'quorum' THEN (node->'policy'->>'quorum')::integer
              ELSE recipients END;
            IF required_votes IS NULL OR required_votes<1 OR votes<required_votes THEN
              RAISE EXCEPTION 'Workflow completion policy not satisfied' USING ERRCODE='55000';
            END IF;
          ELSE
            IF NOT EXISTS(SELECT 1 FROM workflow_actions a WHERE a.step_id=NEW.id
              AND a.kind=CASE WHEN NEW.state='returned' THEN 'return' ELSE 'reject' END) THEN
              RAISE EXCEPTION 'Workflow decision evidence required' USING ERRCODE='55000';
            END IF;
          END IF;
        ELSE
          RAISE EXCEPTION 'Workflow evidence is immutable' USING ERRCODE='55000';
        END IF;
      END IF;
      IF TG_OP='INSERT' AND TG_TABLE_NAME='workflow_instances' THEN
        IF NOT EXISTS(SELECT 1 FROM submissions s JOIN workflow_versions v
          ON v.id=NEW.workflow_version_id WHERE s.id=NEW.submission_id
          AND s.organization_id=NEW.organization_id AND s.workspace_id=NEW.workspace_id
          AND s.owner_id=NEW.owner_id AND s.state='submitted'
          AND s.form_version_id=v.form_version_id AND (v.state='active' OR EXISTS(
            SELECT 1 FROM workflow_revisions r JOIN workflow_instances source
            ON source.id=r.source_instance_id WHERE r.organization_id=NEW.organization_id
            AND r.workspace_id=NEW.workspace_id AND r.submission_id=NEW.submission_id
            AND source.workflow_version_id=NEW.workflow_version_id))) THEN
          RAISE EXCEPTION 'Submitted workflow snapshot required' USING ERRCODE='55000';
        END IF;
      END IF;
      IF TG_OP='INSERT' AND TG_TABLE_NAME='workflow_actions' THEN
        SELECT n INTO node FROM workflow_steps st
          JOIN workflow_instances i ON i.id=st.instance_id
          JOIN workflow_versions v ON v.id=i.workflow_version_id,
          LATERAL jsonb_array_elements(v.definition->'nodes') n
          WHERE st.id=NEW.step_id AND st.state='open' AND i.state='active'
          AND i.current_node=st.node_key AND n->>'key'=st.node_key;
        IF node IS NULL OR NOT EXISTS(SELECT 1 FROM workflow_recipients r
          WHERE r.step_id=NEW.step_id AND r.user_id=NEW.actor_id) THEN
          RAISE EXCEPTION 'Open assigned workflow step required' USING ERRCODE='55000';
        END IF;
        IF NEW.kind IN ('approve','review') AND NEW.kind <> (CASE
          WHEN node->>'kind'='approval' THEN 'approve' ELSE 'review' END) THEN
          RAISE EXCEPTION 'Wrong workflow action kind' USING ERRCODE='55000';
        END IF;
        IF NEW.kind='approve' AND EXISTS(SELECT 1 FROM workflow_instances i
          WHERE i.id=NEW.instance_id AND i.owner_id=NEW.actor_id) THEN
          RAISE EXCEPTION 'Independent approval required' USING ERRCODE='55000';
        END IF;
        IF NEW.kind IN ('approve','review') AND node->'policy'->>'mode'='sequential' THEN
          SELECT count(*) INTO votes FROM workflow_actions a WHERE a.step_id=NEW.step_id;
          IF NOT EXISTS(SELECT 1 FROM workflow_recipients r WHERE r.step_id=NEW.step_id
            AND r.user_id=NEW.actor_id AND r.position=votes) THEN
            RAISE EXCEPTION 'Sequential approval order required' USING ERRCODE='55000';
          END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
OLD_TASK_GUARD = """
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
             OR (OLD.state='in_progress' AND NEW.state IN ('submitted','cancelled')))
        OR (OLD.claimant_id IS NOT NULL AND
           (NEW.claimant_id IS DISTINCT FROM OLD.claimant_id
            OR NEW.submission_id IS DISTINCT FROM OLD.submission_id))
        THEN RAISE EXCEPTION 'Immutable task history/claim' USING ERRCODE='55000'; END IF;
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
NEW_TASK_GUARD = """
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


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "workflow_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_instance_id", sa.Uuid(), nullable=False),
        sa.Column("root_submission_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('correction','amendment') AND length(reason) BETWEEN 1 AND 2000 "
            "AND submission_id <> root_submission_id",
            name=op.f("ck_workflow_revisions_workflow_revision_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "root_submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
            name="fk_workflow_revision_root_owner",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "source_instance_id"],
            [
                "workflow_instances.organization_id",
                "workflow_instances.workspace_id",
                "workflow_instances.id",
            ],
            name=op.f("fk_workflow_revisions_organization_id_workflow_instances"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "submission_id", "owner_id"],
            [
                "submissions.organization_id",
                "submissions.workspace_id",
                "submissions.id",
                "submissions.owner_id",
            ],
            name=op.f("fk_workflow_revisions_organization_id_submissions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_revisions")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_revision_key"),
        sa.UniqueConstraint(
            "organization_id", "source_instance_id", name="uq_workflow_revision_source"
        ),
        sa.UniqueConstraint(
            "organization_id", "submission_id", name="uq_workflow_revision_submission"
        ),
    )
    op.create_index(
        "ix_workflow_revision_scope",
        "workflow_revisions",
        ["organization_id", "workspace_id", "root_submission_id", "id"],
        unique=False,
    )
    op.execute("""
    CREATE FUNCTION protect_workflow_revision() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow revision links are immutable' USING ERRCODE='55000';
      END IF;
      IF NOT EXISTS(
        SELECT 1 FROM workflow_instances source
        JOIN submissions prior ON prior.id=source.submission_id
        JOIN submissions draft ON draft.id=NEW.submission_id
        LEFT JOIN workflow_revisions parent ON parent.submission_id=source.submission_id
          AND parent.organization_id=source.organization_id
        WHERE source.id=NEW.source_instance_id AND source.organization_id=NEW.organization_id
          AND source.workspace_id=NEW.workspace_id AND source.owner_id=NEW.owner_id
          AND draft.organization_id=NEW.organization_id AND draft.workspace_id=NEW.workspace_id
          AND draft.owner_id=NEW.owner_id AND draft.state='draft'
          AND draft.form_version_id=prior.form_version_id
          AND NEW.root_submission_id=coalesce(parent.root_submission_id,source.submission_id)
          AND ((NEW.kind='correction' AND source.state IN ('returned','rejected'))
            OR (NEW.kind='amendment' AND source.state IN ('approved','closed')))
      ) THEN RAISE EXCEPTION 'Exact governed workflow revision required'
        USING ERRCODE='55000'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER protect_workflow_revisions BEFORE INSERT OR UPDATE OR DELETE
      ON workflow_revisions FOR EACH ROW EXECUTE FUNCTION protect_workflow_revision();
    CREATE TRIGGER protect_workflow_revisions_truncate BEFORE TRUNCATE
      ON workflow_revisions FOR EACH STATEMENT EXECUTE FUNCTION protect_workflow_revision();
    """)
    op.execute(NEW_RUNTIME_GUARD)
    op.execute(NEW_TASK_GUARD)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM workflow_revisions) OR EXISTS(
        SELECT 1 FROM task_occurrences WHERE state IN ('awaiting_review','returned','approved')
      ) THEN RAISE EXCEPTION 'Populated workflow revision/task downgrade refused'
        USING ERRCODE='55000'; END IF;
    END $$;
    """)
    op.execute(OLD_RUNTIME_GUARD)
    op.execute(OLD_TASK_GUARD)
    op.execute("DROP FUNCTION protect_workflow_revision() CASCADE")

    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_workflow_revision_scope", table_name="workflow_revisions")
    op.drop_table("workflow_revisions")
    # ### end Alembic commands ###
