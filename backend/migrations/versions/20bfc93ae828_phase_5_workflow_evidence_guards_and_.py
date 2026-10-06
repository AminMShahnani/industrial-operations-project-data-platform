"""phase 5 workflow evidence guards and history bounds"""

import sqlalchemy as sa
from alembic import op

revision = "20bfc93ae828"
down_revision = "c4f0276864fa"
branch_labels = None
depends_on = None

OLD_GUARD = """
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

NEW_GUARD = """
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
        IF NEW.state <> 'active' OR NEW.revision <> 1 OR NOT EXISTS(
          SELECT 1 FROM workflow_versions v,
            LATERAL jsonb_array_elements(v.definition->'nodes') n
          WHERE v.id=NEW.workflow_version_id AND n->>'key'=NEW.current_node
            AND n->>'kind'='start'
        ) THEN RAISE EXCEPTION 'Workflow instance must start at its pinned start node'
          USING ERRCODE='55000'; END IF;
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
        IF node->'policy'->>'mode'='sequential' THEN
          SELECT count(*) INTO votes FROM workflow_actions a WHERE a.step_id=NEW.step_id;
          IF NOT EXISTS(SELECT 1 FROM workflow_recipients r WHERE r.step_id=NEW.step_id
            AND r.user_id=NEW.actor_id AND r.position=votes) THEN
            RAISE EXCEPTION 'Sequential approval order required' USING ERRCODE='55000';
          END IF;
        END IF;
      END IF;
      IF TG_TABLE_NAME='workflow_steps' AND TG_OP='INSERT' THEN
        IF NEW.state <> 'open' OR NEW.number <> (
          SELECT count(*)+1 FROM workflow_steps s WHERE s.instance_id=NEW.instance_id
        ) OR NOT EXISTS(
          SELECT 1 FROM workflow_instances i JOIN workflow_versions v
            ON v.id=i.workflow_version_id,
            LATERAL jsonb_array_elements(v.definition->'nodes') n
          WHERE i.id=NEW.instance_id AND i.state='active'
            AND n->>'key'=NEW.node_key AND n->>'kind' IN ('review','approval')
        ) THEN RAISE EXCEPTION 'Exact open workflow visit required'
          USING ERRCODE='55000'; END IF;
      END IF;
      IF TG_TABLE_NAME='workflow_recipients' AND TG_OP='INSERT' THEN
        IF NEW.position <> (SELECT count(*) FROM workflow_recipients r
            WHERE r.step_id=NEW.step_id) OR NOT EXISTS(
          SELECT 1 FROM workflow_steps s JOIN workflow_instances i ON i.id=s.instance_id
            JOIN workflow_versions v ON v.id=i.workflow_version_id
            JOIN users u ON u.id=NEW.user_id AND u.organization_id=NEW.organization_id,
            LATERAL jsonb_array_elements(v.definition->'nodes') n
          WHERE s.id=NEW.step_id AND s.state='open' AND i.state='active' AND u.active
            AND n->>'key'=s.node_key
            AND (n->>'kind'<>'approval' OR i.owner_id<>NEW.user_id)
        ) THEN RAISE EXCEPTION 'Exact eligible independent recipient snapshot required'
          USING ERRCODE='55000'; END IF;
      END IF;
      IF TG_TABLE_NAME='workflow_instances' THEN
        IF NEW.state IN ('approved','closed') THEN
          IF NOT EXISTS(
            SELECT 1 FROM workflow_versions v,
              LATERAL jsonb_array_elements(v.definition->'nodes') n
            WHERE v.id=NEW.workflow_version_id AND n->>'key'=NEW.current_node
              AND n->>'kind'='end'
          ) OR EXISTS(SELECT 1 FROM workflow_steps s
            WHERE s.instance_id=NEW.id AND s.state='open') THEN
            RAISE EXCEPTION 'Workflow closure requires a completed end path'
              USING ERRCODE='55000'; END IF;
          IF (NEW.state='approved') IS DISTINCT FROM EXISTS(
            SELECT 1 FROM workflow_steps s JOIN workflow_versions v
              ON v.id=NEW.workflow_version_id,
              LATERAL jsonb_array_elements(v.definition->'nodes') n
            WHERE s.instance_id=NEW.id AND s.state='completed'
              AND n->>'key'=s.node_key AND n->>'kind'='approval'
          ) THEN RAISE EXCEPTION 'Workflow approval evidence required'
            USING ERRCODE='55000'; END IF;
        ELSIF NEW.state IN ('returned','rejected') THEN
          IF NOT EXISTS(SELECT 1 FROM workflow_steps s WHERE s.instance_id=NEW.id
            AND s.node_key=NEW.current_node AND s.state IN ('returned','rejected')) THEN
            RAISE EXCEPTION 'Workflow return/reject evidence required'
              USING ERRCODE='55000'; END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_workflow_steps_workflow_step_state"), "workflow_steps", type_="check"
    )
    op.create_check_constraint(
        "workflow_step_state",
        "workflow_steps",
        "number BETWEEN 1 AND 1000 AND state IN ('open','completed','returned','rejected')",
    )
    op.drop_constraint(
        op.f("ck_workflow_recipients_workflow_recipient_position"),
        "workflow_recipients",
        type_="check",
    )
    op.create_check_constraint(
        "workflow_recipient_position", "workflow_recipients", "position BETWEEN 0 AND 999"
    )
    op.create_index(
        "uq_workflow_open_step",
        "workflow_steps",
        ["organization_id", "workspace_id", "instance_id"],
        unique=True,
        postgresql_where=sa.text("state='open'"),
    )
    op.execute(NEW_GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM workflow_instances) THEN
        RAISE EXCEPTION 'Populated workflow guard downgrade refused; restore/reconcile backup'
          USING ERRCODE='55000'; END IF;
    END $$;
    """)
    op.execute(OLD_GUARD)
    op.drop_index("uq_workflow_open_step", table_name="workflow_steps")
    op.drop_constraint(
        op.f("ck_workflow_steps_workflow_step_state"), "workflow_steps", type_="check"
    )
    op.create_check_constraint(
        "workflow_step_state",
        "workflow_steps",
        "number > 0 AND state IN ('open','completed','returned','rejected')",
    )
    op.drop_constraint(
        op.f("ck_workflow_recipients_workflow_recipient_position"),
        "workflow_recipients",
        type_="check",
    )
    op.create_check_constraint(
        "workflow_recipient_position", "workflow_recipients", "position >= 0"
    )
