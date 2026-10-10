"""Immutable scoped webhook endpoint versions with audited rollback guard."""

import sqlalchemy as sa
from alembic import op

revision = "f27d9a48c6b1"
down_revision = "e49b7d83af20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_endpoint_versions",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret_reference", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_webhook_endpoint_versions_webhook_endpoint_version_positive"),
        ),
        sa.CheckConstraint(
            "state IN ('active','revoked') AND ((project_id IS NULL AND workspace_id IS NULL) "
            "OR workspace_id IS NOT NULL)",
            name=op.f("ck_webhook_endpoint_versions_webhook_endpoint_scope_state"),
        ),
        sa.CheckConstraint(
            "url LIKE 'https://%' AND char_length(name) BETWEEN 1 AND 120 "
            "AND char_length(secret_reference) BETWEEN 1 AND 512",
            name=op.f("ck_webhook_endpoint_versions_webhook_endpoint_values"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_webhook_endpoint_versions_organization_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
            name=op.f("fk_webhook_endpoint_versions_organization_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_webhook_endpoint_versions_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_webhook_endpoint_versions_organization_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["audit_events.id"],
            name=op.f("fk_webhook_endpoint_versions_organization_id_audit_events"),
        ),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_webhook_endpoint_versions")),
        sa.UniqueConstraint(
            "organization_id", "endpoint_id", "version", name="uq_webhook_endpoint_version"
        ),
    )
    op.create_index(
        "ix_webhook_endpoint_scope_cursor",
        "webhook_endpoint_versions",
        ["organization_id", "workspace_id", "project_id", "endpoint_id", "version"],
    )
    op.execute("""CREATE FUNCTION protect_webhook_endpoint_version() RETURNS trigger
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
    op.execute("""CREATE TRIGGER webhook_endpoint_version_insert_guard
      BEFORE INSERT OR UPDATE OR DELETE ON webhook_endpoint_versions
      FOR EACH ROW EXECUTE FUNCTION protect_webhook_endpoint_version()""")
    op.execute("""CREATE TRIGGER webhook_endpoint_version_truncate_guard
      BEFORE TRUNCATE ON webhook_endpoint_versions FOR EACH STATEMENT
      EXECUTE FUNCTION protect_webhook_endpoint_version()""")


def downgrade() -> None:
    op.execute("LOCK TABLE webhook_endpoint_versions IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM webhook_endpoint_versions) THEN
      RAISE EXCEPTION 'Retained webhook endpoint history prevents rollback; restore backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_table("webhook_endpoint_versions")
    op.execute("DROP FUNCTION protect_webhook_endpoint_version()")
