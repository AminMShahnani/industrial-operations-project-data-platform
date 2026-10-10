"""Phase 6 explicit email channel capture and inbox visibility."""

import sqlalchemy as sa
from alembic import op

revision = "5caef6ad5721"
down_revision = "208f826ca492"
branch_labels = None
depends_on = None

OLD_GUARD = """CREATE OR REPLACE FUNCTION notification_insert_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM automation_runs r
        JOIN outbox_events e ON e.id=r.event_id AND e.organization_id=r.organization_id
        JOIN automation_versions v ON v.id=r.rule_version_id AND v.organization_id=r.organization_id
        WHERE r.id=NEW.run_id AND r.organization_id=NEW.organization_id
          AND r.event_id=NEW.event_id AND r.state IN ('pending','retry')
          AND e.workspace_id=NEW.workspace_id AND e.project_id IS NOT DISTINCT FROM NEW.project_id
          AND v.definition->'actions'->NEW.position->>'kind'='notify'
          AND v.definition->'actions'->NEW.position->'channels'='["in_app"]'::jsonb
          AND v.definition->'actions'->NEW.position->'recipients'
              @> to_jsonb(NEW.recipient_id::text)
          AND v.definition->'actions'->NEW.position->>'topic'=NEW.topic
          AND NEW.created_at >= e.occurred_at
          AND ((NEW.source_kind='task'
                AND e.envelope->'payload'->>'task_id'=NEW.source_id::text)
            OR (NEW.source_kind='workflow' AND e.envelope->'payload'->>'task_id' IS NULL
                AND e.envelope->'payload'->>'workflow_instance_id'=NEW.source_id::text)
            OR (NEW.source_kind='submission' AND e.envelope->'payload'->>'task_id' IS NULL
                AND e.envelope->'payload'->>'workflow_instance_id' IS NULL
                AND e.envelope->'payload'->>'submission_id'=NEW.source_id::text)
            OR (NEW.source_kind='project' AND e.envelope->>'aggregate_type'='project'
                AND e.envelope->>'aggregate_id'=NEW.source_id::text
                AND e.project_id=NEW.source_id))
          AND (NEW.topic='rule_notice' OR (NEW.topic='work_assigned' AND NEW.source_kind='task')
            OR (NEW.topic='review_requested' AND NEW.source_kind='workflow'))
          AND EXISTS (SELECT 1 FROM audit_events a WHERE a.organization_id=NEW.organization_id
            AND a.aggregate_id=NEW.id AND a.type='notification.created'
            AND a.payload->>'run_id'=NEW.run_id::text
            AND a.payload->>'target_id'=NEW.recipient_id::text
            AND a.payload->>'workspace_id'=NEW.workspace_id::text)
      ) THEN RAISE EXCEPTION 'Invalid notification source/action evidence'
        USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
"""
NEW_GUARD = """CREATE OR REPLACE FUNCTION notification_insert_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM automation_runs r
        JOIN outbox_events e ON e.id=r.event_id AND e.organization_id=r.organization_id
        JOIN automation_versions v ON v.id=r.rule_version_id AND v.organization_id=r.organization_id
        WHERE r.id=NEW.run_id AND r.organization_id=NEW.organization_id
          AND r.event_id=NEW.event_id AND r.state IN ('pending','retry')
          AND e.workspace_id=NEW.workspace_id AND e.project_id IS NOT DISTINCT FROM NEW.project_id
          AND v.definition->'actions'->NEW.position->>'kind'='notify'
          AND v.definition->'actions'->NEW.position->'channels' <@ '["in_app","email"]'::jsonb
          AND jsonb_array_length(v.definition->'actions'->NEW.position->'channels') BETWEEN 1 AND 2
          AND NEW.in_app =
            (v.definition->'actions'->NEW.position->'channels' @> '["in_app"]'::jsonb)
          AND v.definition->'actions'->NEW.position->'recipients'
              @> to_jsonb(NEW.recipient_id::text)
          AND v.definition->'actions'->NEW.position->>'topic'=NEW.topic
          AND NEW.created_at >= e.occurred_at
          AND ((NEW.source_kind='task'
                AND e.envelope->'payload'->>'task_id'=NEW.source_id::text)
            OR (NEW.source_kind='workflow' AND e.envelope->'payload'->>'task_id' IS NULL
                AND e.envelope->'payload'->>'workflow_instance_id'=NEW.source_id::text)
            OR (NEW.source_kind='submission' AND e.envelope->'payload'->>'task_id' IS NULL
                AND e.envelope->'payload'->>'workflow_instance_id' IS NULL
                AND e.envelope->'payload'->>'submission_id'=NEW.source_id::text)
            OR (NEW.source_kind='project' AND e.envelope->>'aggregate_type'='project'
                AND e.envelope->>'aggregate_id'=NEW.source_id::text
                AND e.project_id=NEW.source_id))
          AND (NEW.topic='rule_notice' OR (NEW.topic='work_assigned' AND NEW.source_kind='task')
            OR (NEW.topic='review_requested' AND NEW.source_kind='workflow'))
          AND EXISTS (SELECT 1 FROM audit_events a WHERE a.organization_id=NEW.organization_id
            AND a.aggregate_id=NEW.id AND a.type='notification.created'
            AND a.payload->>'run_id'=NEW.run_id::text
            AND a.payload->>'target_id'=NEW.recipient_id::text
            AND a.payload->>'workspace_id'=NEW.workspace_id::text)
      ) THEN RAISE EXCEPTION 'Invalid notification source/action evidence'
        USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
"""


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("in_app", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_check_constraint(
        "ck_notifications_notice_automatic_in_app", "notifications", "origin='automation' OR in_app"
    )
    op.create_index(
        "ix_notice_visible_cursor",
        "notifications",
        ["organization_id", "workspace_id", "recipient_id", "created_at", "id"],
        postgresql_where=sa.text("in_app"),
    )
    op.execute(NEW_GUARD)
    op.execute("""
    CREATE FUNCTION notification_visible_read_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM notifications n WHERE n.organization_id=NEW.organization_id
        AND n.id=NEW.notice_id AND n.recipient_id=NEW.recipient_id AND n.in_app)
      THEN RAISE EXCEPTION 'Email-only notice cannot be marked read' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER notification_visible_read_guard BEFORE INSERT ON notification_reads
      FOR EACH ROW EXECUTE FUNCTION notification_visible_read_guard();
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
      SELECT EXISTS (SELECT 1 FROM notifications WHERE NOT in_app) OR EXISTS (
        SELECT 1 FROM automation_versions WHERE jsonb_path_exists(
          definition, '$.actions[*].channels[*] ? (@ == "email")'))
    """)
    ):
        raise RuntimeError(
            "Email channel evidence exists; forward fix or verified restore required"
        )
    op.execute("DROP TRIGGER notification_visible_read_guard ON notification_reads")
    op.execute("DROP FUNCTION notification_visible_read_guard()")
    op.execute(OLD_GUARD)
    op.drop_index("ix_notice_visible_cursor", table_name="notifications")
    op.drop_constraint("ck_notifications_notice_automatic_in_app", "notifications", type_="check")
    op.drop_column("notifications", "in_app")
