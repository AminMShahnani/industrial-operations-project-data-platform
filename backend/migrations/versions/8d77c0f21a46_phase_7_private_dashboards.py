"""Add creator-private, immutable dashboard definitions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8d77c0f21a46"
down_revision = "41a9c1d7e5b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_versions",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_dashboard_versions")),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_dashboard_versions_workspace"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_dashboard_versions_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_dashboard_versions_audit"),
        ),
        sa.UniqueConstraint(
            "organization_id", "dashboard_id", "version", name="uq_dashboard_version"
        ),
        sa.UniqueConstraint(
            "organization_id", "dashboard_id", "audit_id", name="uq_dashboard_audit"
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_dashboard_versions_version_positive")),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120 AND char_length(definition_sha256)=64",
            name=op.f("ck_dashboard_versions_values"),
        ),
    )
    op.create_index(
        "ix_dashboard_owner_scope",
        "dashboard_versions",
        ["organization_id", "workspace_id", "owner_id", "dashboard_id", "version"],
    )
    op.create_table(
        "dashboard_states",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id", "dashboard_id", name=op.f("pk_dashboard_states")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_dashboard_states_audit"),
        ),
    )
    op.execute("""CREATE FUNCTION protect_dashboard_version() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP<>'INSERT' THEN
          RAISE EXCEPTION 'Dashboard definition history is retained' USING ERRCODE='55000';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM audit_events a
          WHERE a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
          AND a.aggregate_type='dashboard' AND a.aggregate_id=NEW.dashboard_id
          AND a.type IN ('report.dashboard.created','report.dashboard.updated')
          AND a.actor_id=NEW.owner_id AND a.occurred_at=NEW.created_at
          AND a.payload->>'target_id'=NEW.dashboard_id::text
          AND a.payload->>'workspace_id'=NEW.workspace_id::text
          AND a.payload->>'version'=NEW.version::text)
        THEN
          RAISE EXCEPTION 'Dashboard version requires exact audit' USING ERRCODE='23514';
        END IF;
        IF NEW.version=1 THEN
          IF NEW.name IS NULL THEN
            RAISE EXCEPTION 'Invalid dashboard identity' USING ERRCODE='23514';
          END IF;
        ELSIF NOT EXISTS (SELECT 1 FROM dashboard_versions p
          WHERE p.organization_id=NEW.organization_id AND p.dashboard_id=NEW.dashboard_id
          AND p.version=NEW.version-1 AND p.workspace_id=NEW.workspace_id
          AND p.owner_id=NEW.owner_id)
        THEN
          RAISE EXCEPTION 'Dashboard owner and scope are immutable' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;""")
    op.execute("""CREATE FUNCTION protect_dashboard_state() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='TRUNCATE' THEN
          RAISE EXCEPTION 'Dashboard state is retained' USING ERRCODE='55000';
        END IF;
        IF TG_OP='DELETE' THEN
          RAISE EXCEPTION 'Dashboard state is retained' USING ERRCODE='55000';
        END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.archived OR NOT EXISTS (SELECT 1 FROM dashboard_versions v
            WHERE v.organization_id=NEW.organization_id AND v.dashboard_id=NEW.dashboard_id
            AND v.audit_id=NEW.audit_id AND v.version=1)
          THEN RAISE EXCEPTION 'Invalid initial dashboard state' USING ERRCODE='23514'; END IF;
        ELSE
          IF OLD.archived OR NOT EXISTS (SELECT 1 FROM dashboard_versions v
            JOIN audit_events a ON a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
            WHERE v.organization_id=OLD.organization_id AND v.dashboard_id=OLD.dashboard_id
            AND v.audit_id=OLD.audit_id AND a.aggregate_type='dashboard'
            AND a.aggregate_id=NEW.dashboard_id AND a.payload->>'target_id'=NEW.dashboard_id::text
            AND a.payload->>'workspace_id'=v.workspace_id::text
            AND a.actor_id=v.owner_id AND a.occurred_at=NEW.updated_at
            AND ((NOT NEW.archived AND a.type='report.dashboard.updated'
              AND a.payload->>'version'=(SELECT max(version)::text FROM dashboard_versions
                WHERE organization_id=NEW.organization_id AND dashboard_id=NEW.dashboard_id))
              OR (NEW.archived AND a.type='report.dashboard.archived'
              AND a.payload->>'version'=(SELECT max(version)::text FROM dashboard_versions
                WHERE organization_id=NEW.organization_id AND dashboard_id=NEW.dashboard_id))))
          THEN RAISE EXCEPTION 'Dashboard state requires exact audit' USING ERRCODE='23514'; END IF;
        END IF;
        RETURN NEW;
      END $$;""")
    op.execute(
        "CREATE TRIGGER protect_dashboard_versions BEFORE INSERT OR UPDATE OR DELETE "
        "ON dashboard_versions FOR EACH ROW EXECUTE FUNCTION protect_dashboard_version()"
    )
    op.execute(
        "CREATE TRIGGER protect_dashboard_versions_truncate BEFORE TRUNCATE "
        "ON dashboard_versions FOR EACH STATEMENT EXECUTE FUNCTION protect_dashboard_version()"
    )
    op.execute(
        "CREATE TRIGGER protect_dashboard_states BEFORE INSERT OR UPDATE OR DELETE "
        "ON dashboard_states FOR EACH ROW EXECUTE FUNCTION protect_dashboard_state()"
    )
    op.execute(
        "CREATE TRIGGER protect_dashboard_states_truncate BEFORE TRUNCATE "
        "ON dashboard_states FOR EACH STATEMENT EXECUTE FUNCTION protect_dashboard_state()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE dashboard_versions, dashboard_states IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM dashboard_versions)
      OR EXISTS (SELECT 1 FROM dashboard_states) THEN
      RAISE EXCEPTION 'Dashboard history prevents rollback; restore a verified backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_table("dashboard_states")
    op.drop_index("ix_dashboard_owner_scope", table_name="dashboard_versions")
    op.drop_table("dashboard_versions")
    op.execute("DROP FUNCTION protect_dashboard_state()")
    op.execute("DROP FUNCTION protect_dashboard_version()")
