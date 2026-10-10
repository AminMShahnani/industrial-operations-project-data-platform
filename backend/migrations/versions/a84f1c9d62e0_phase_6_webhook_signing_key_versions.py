"""Pin external webhook signing key versions in immutable endpoint history."""

import sqlalchemy as sa
from alembic import op

revision = "a84f1c9d62e0"
down_revision = "f27d9a48c6b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Previously-created endpoint rows had no key version. Delivery has not yet
    # been enabled, so retain those rows with explicit version 1 and no data loss.
    op.add_column(
        "webhook_endpoint_versions",
        sa.Column("signing_key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("webhook_endpoint_versions", "signing_key_version", server_default=None)
    op.create_check_constraint(
        "ck_webhook_endpoint_versions_webhook_endpoint_signing_key_version_positive",
        "webhook_endpoint_versions",
        "signing_key_version > 0",
    )
    op.execute("""CREATE OR REPLACE FUNCTION protect_webhook_endpoint_version() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE expected_action text;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Webhook endpoint versions are immutable'
          USING ERRCODE='55000';
      END IF;
      expected_action := CASE
        WHEN NEW.state='revoked' THEN 'revoked'
        WHEN NEW.version=1 THEN 'created'
        ELSE 'versioned'
      END;
      IF NOT EXISTS (SELECT 1 FROM audit_events a
        WHERE a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
          AND a.type='integration.webhook_endpoint.' || expected_action
          AND a.actor_id=NEW.created_by_id AND a.occurred_at=NEW.created_at
          AND a.aggregate_type='webhook_endpoint' AND a.aggregate_id=NEW.endpoint_id
          AND a.payload->>'target_id'=NEW.endpoint_id::text
          AND a.payload->>'version'=NEW.version::text
          AND a.payload->>'signing_key_version'=NEW.signing_key_version::text
          AND a.payload->>'workspace_id' IS NOT DISTINCT FROM
            CASE WHEN NEW.workspace_id IS NULL THEN NULL ELSE NEW.workspace_id::text END
          AND a.payload->>'project_id' IS NOT DISTINCT FROM
            CASE WHEN NEW.project_id IS NULL THEN NULL ELSE NEW.project_id::text END
          AND a.payload->>'scope_type' = CASE
            WHEN NEW.workspace_id IS NULL THEN 'organization' ELSE 'workspace' END
          AND a.payload->>'scope_id' = CASE
            WHEN NEW.workspace_id IS NULL THEN NEW.organization_id::text
            ELSE NEW.workspace_id::text END) THEN
        RAISE EXCEPTION 'Webhook endpoint version requires exact audit evidence'
          USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")


def downgrade() -> None:
    op.execute("LOCK TABLE webhook_endpoint_versions IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM webhook_endpoint_versions) THEN
      RAISE EXCEPTION 'Retained webhook signing key versions prevent rollback; restore backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_constraint(
        "ck_webhook_endpoint_versions_webhook_endpoint_signing_key_version_positive",
        "webhook_endpoint_versions",
        type_="check",
    )
    op.drop_column("webhook_endpoint_versions", "signing_key_version")
    op.execute("""CREATE OR REPLACE FUNCTION protect_webhook_endpoint_version() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE expected_action text;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Webhook endpoint versions are immutable'
          USING ERRCODE='55000';
      END IF;
      expected_action := CASE
        WHEN NEW.state='revoked' THEN 'revoked'
        WHEN NEW.version=1 THEN 'created'
        ELSE 'versioned'
      END;
      IF NOT EXISTS (SELECT 1 FROM audit_events a
        WHERE a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
          AND a.type='integration.webhook_endpoint.' || expected_action
          AND a.actor_id=NEW.created_by_id AND a.occurred_at=NEW.created_at
          AND a.aggregate_type='webhook_endpoint' AND a.aggregate_id=NEW.endpoint_id
          AND a.payload->>'target_id'=NEW.endpoint_id::text
          AND a.payload->>'version'=NEW.version::text
          AND a.payload->>'workspace_id' IS NOT DISTINCT FROM
            CASE WHEN NEW.workspace_id IS NULL THEN NULL ELSE NEW.workspace_id::text END
          AND a.payload->>'project_id' IS NOT DISTINCT FROM
            CASE WHEN NEW.project_id IS NULL THEN NULL ELSE NEW.project_id::text END
          AND a.payload->>'scope_type' = CASE
            WHEN NEW.workspace_id IS NULL THEN 'organization' ELSE 'workspace' END
          AND a.payload->>'scope_id' = CASE
            WHEN NEW.workspace_id IS NULL THEN NEW.organization_id::text
            ELSE NEW.workspace_id::text END) THEN
        RAISE EXCEPTION 'Webhook endpoint version requires exact audit evidence'
          USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")
