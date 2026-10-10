"""Persist identifiers-only webhook intents in automation action transactions."""

import sqlalchemy as sa
from alembic import op

revision = "d62a1f48c0e1"
down_revision = "a84f1c9d62e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_delivery_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("action_position", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_version", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action_position BETWEEN 0 AND 19 AND endpoint_version > 0 "
            "AND workspace_id IS NOT NULL",
            name="webhook_intent_scope_position",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "event_id"],
            ["outbox_events.organization_id", "outbox_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["automation_runs.organization_id", "automation_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "rule_version_id"],
            ["automation_versions.organization_id", "automation_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "endpoint_id", "endpoint_version"],
            [
                "webhook_endpoint_versions.organization_id",
                "webhook_endpoint_versions.endpoint_id",
                "webhook_endpoint_versions.version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requested_by_id"], ["users.organization_id", "users.id"]
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_delivery_intents")),
        sa.UniqueConstraint("audit_id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint(
            "organization_id", "run_id", "action_position", name="uq_webhook_intent_action"
        ),
    )
    op.create_index(
        "ix_webhook_intent_scope_created",
        "webhook_delivery_intents",
        ["organization_id", "workspace_id", "created_at", "id"],
    )
    op.execute("""CREATE FUNCTION protect_webhook_intent() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Webhook delivery intents are immutable'
          USING ERRCODE='55000';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM audit_events a
        WHERE a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
          AND a.type='integration.webhook.intent.created'
          AND a.actor_id=NEW.requested_by_id AND a.occurred_at=NEW.created_at
          AND a.request_id=NEW.run_id AND a.correlation_id=NEW.correlation_id
          AND a.aggregate_type='webhook_delivery' AND a.aggregate_id=NEW.id
          AND a.payload->>'target_id'=NEW.endpoint_id::text
          AND a.payload->>'version'=NEW.endpoint_version::text
          AND a.payload->>'workspace_id'=NEW.workspace_id::text
          AND a.payload->>'project_id' IS NOT DISTINCT FROM
            CASE WHEN NEW.project_id IS NULL THEN NULL ELSE NEW.project_id::text END
          AND a.payload->>'scope_type'='workspace'
          AND a.payload->>'scope_id'=NEW.workspace_id::text
          AND a.payload->>'run_id'=NEW.run_id::text
          AND a.payload->>'rule_version_id'=NEW.rule_version_id::text
          AND a.payload->>'authorization_kind'='delegated_automation'
          AND a.payload->>'outcome'='intent_created') THEN
        RAISE EXCEPTION 'Webhook delivery intent requires exact audit evidence'
          USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")
    op.execute("""CREATE TRIGGER webhook_intent_insert_guard
      BEFORE INSERT OR UPDATE OR DELETE ON webhook_delivery_intents
      FOR EACH ROW EXECUTE FUNCTION protect_webhook_intent()""")
    op.execute("""CREATE TRIGGER webhook_intent_truncate_guard
      BEFORE TRUNCATE ON webhook_delivery_intents FOR EACH STATEMENT
      EXECUTE FUNCTION protect_webhook_intent()""")


def downgrade() -> None:
    op.execute("LOCK TABLE webhook_delivery_intents IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM webhook_delivery_intents) THEN
      RAISE EXCEPTION 'Retained webhook intents prevent rollback; restore backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_table("webhook_delivery_intents")
    op.execute("DROP FUNCTION protect_webhook_intent()")
