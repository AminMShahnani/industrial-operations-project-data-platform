"""Track webhook delivery claims, outcomes and immutable attempts."""

import sqlalchemy as sa
from alembic import op

revision = "ee31ac92bf10"
down_revision = "d62a1f48c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_delivery_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sending','retry','sent','failed','uncertain','skipped') "
            "AND attempts BETWEEN 0 AND 20",
            name="webhook_delivery_status_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "id"],
            ["webhook_delivery_intents.organization_id", "webhook_delivery_intents.id"],
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id", "organization_id"),
    )
    op.create_index(
        "ix_webhook_delivery_due", "webhook_delivery_states", ["status", "next_at", "id"]
    )
    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "number BETWEEN 1 AND 20 AND outcome IN "
            "('sent','retry','failed','uncertain','skipped')",
            name="webhook_attempt_values",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "delivery_id"],
            ["webhook_delivery_states.organization_id", "webhook_delivery_states.id"],
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_delivery_attempts")),
        sa.UniqueConstraint("audit_id"),
        sa.UniqueConstraint("organization_id", "delivery_id", "number"),
    )
    op.create_index(
        "ix_webhook_attempt_cursor",
        "webhook_delivery_attempts",
        ["organization_id", "delivery_id", "number"],
    )
    op.execute("""CREATE FUNCTION protect_webhook_delivery_state() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='INSERT' THEN
        IF NEW.status <> 'pending' OR NEW.attempts <> 0 OR NOT EXISTS (
          SELECT 1 FROM webhook_delivery_intents i WHERE i.organization_id=NEW.organization_id
            AND i.id=NEW.id AND i.audit_id=NEW.audit_id) THEN
          RAISE EXCEPTION 'Initial webhook state must match the immutable intent'
            USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END IF;
      IF TG_OP='UPDATE' AND EXISTS (SELECT 1 FROM audit_events a
        WHERE a.id=NEW.audit_id AND a.organization_id=NEW.organization_id
          AND a.type='integration.webhook.delivery.updated'
          AND a.occurred_at=NEW.updated_at AND a.request_id=NEW.id
          AND a.correlation_id=(SELECT i.correlation_id FROM webhook_delivery_intents i
            WHERE i.organization_id=NEW.organization_id AND i.id=NEW.id)
          AND a.aggregate_type='webhook_delivery' AND a.aggregate_id=NEW.id
          AND a.payload->>'outcome'=NEW.status
          AND a.payload->>'version'=NEW.attempts::text) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Webhook delivery state requires matching audit evidence'
        USING ERRCODE='55000';
    END $$""")
    op.execute("""CREATE TRIGGER webhook_delivery_state_guard
      BEFORE INSERT OR UPDATE OR DELETE ON webhook_delivery_states
      FOR EACH ROW EXECUTE FUNCTION protect_webhook_delivery_state()""")
    op.execute("""CREATE TRIGGER webhook_delivery_state_truncate_guard
      BEFORE TRUNCATE ON webhook_delivery_states FOR EACH STATEMENT
      EXECUTE FUNCTION protect_webhook_delivery_state()""")
    op.execute("""CREATE FUNCTION protect_webhook_attempt() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='INSERT' AND EXISTS (SELECT 1 FROM audit_events a
        JOIN webhook_delivery_intents i ON i.organization_id=a.organization_id
          AND i.id=NEW.delivery_id
        WHERE a.id=NEW.audit_id AND a.type='integration.webhook.attempted'
          AND a.occurred_at=NEW.finished_at AND a.request_id=NEW.delivery_id
          AND a.correlation_id=i.correlation_id AND a.aggregate_type='webhook_delivery'
          AND a.aggregate_id=NEW.delivery_id AND a.payload->>'outcome'=NEW.outcome
          AND a.payload->>'version'=NEW.number::text) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Webhook attempts are immutable and require exact audit evidence'
        USING ERRCODE='55000';
    END $$""")
    op.execute("""CREATE TRIGGER webhook_attempt_guard
      BEFORE INSERT OR UPDATE OR DELETE ON webhook_delivery_attempts
      FOR EACH ROW EXECUTE FUNCTION protect_webhook_attempt()""")
    op.execute("""CREATE TRIGGER webhook_attempt_truncate_guard
      BEFORE TRUNCATE ON webhook_delivery_attempts FOR EACH STATEMENT
      EXECUTE FUNCTION protect_webhook_attempt()""")


def downgrade() -> None:
    op.execute(
        "LOCK TABLE webhook_delivery_attempts, webhook_delivery_states IN ACCESS EXCLUSIVE MODE"
    )
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM webhook_delivery_attempts)
      OR EXISTS (SELECT 1 FROM webhook_delivery_states) THEN
      RAISE EXCEPTION 'Retained webhook delivery history prevents rollback; restore backup'
        USING ERRCODE='55000'; END IF; END $$""")
    op.drop_table("webhook_delivery_attempts")
    op.drop_table("webhook_delivery_states")
    op.execute("DROP FUNCTION protect_webhook_attempt()")
    op.execute("DROP FUNCTION protect_webhook_delivery_state()")
