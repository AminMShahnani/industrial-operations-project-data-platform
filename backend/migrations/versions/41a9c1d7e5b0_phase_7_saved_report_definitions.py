"""Store private, audited, immutable saved report definitions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "41a9c1d7e5b0"
down_revision = "fc5310a0d279"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_report_identities",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id", "report_id", name=op.f("pk_saved_report_identities")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_saved_report_identities_org")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_saved_report_identities_workspace"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_saved_report_identities_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_saved_report_identities_audit"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
            name=op.f("fk_saved_report_identities_project"),
        ),
    )
    op.create_table(
        "saved_report_versions",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_saved_report_versions")),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_saved_report_versions_workspace"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_saved_report_versions_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_saved_report_versions_audit"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
            name=op.f("fk_saved_report_versions_project"),
        ),
        sa.UniqueConstraint(
            "organization_id", "report_id", "version", name="uq_saved_report_version"
        ),
        sa.UniqueConstraint(
            "organization_id", "report_id", "audit_id", name="uq_saved_report_audit"
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_saved_report_versions_version_positive")),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120 AND char_length(definition_sha256)=64",
            name=op.f("ck_saved_report_versions_values"),
        ),
    )
    op.create_index(
        "ix_saved_report_owner_scope",
        "saved_report_versions",
        ["organization_id", "workspace_id", "owner_id", "report_id", "version"],
    )
    op.create_table(
        "saved_report_states",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint(
            "organization_id", "report_id", name=op.f("pk_saved_report_states")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_saved_report_states_audit"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "report_id"],
            ["saved_report_identities.organization_id", "saved_report_identities.report_id"],
            name=op.f("fk_saved_report_states_identity"),
        ),
    )
    op.execute("""CREATE FUNCTION protect_saved_report_version() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP<>'INSERT' THEN
        RAISE EXCEPTION 'Saved report definition history is retained' USING ERRCODE='55000';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.organization_id=NEW.organization_id
        AND a.id=NEW.audit_id AND a.aggregate_type='saved_report' AND a.aggregate_id=NEW.report_id
        AND a.type IN ('report.saved_definition.created','report.saved_definition.updated')
        AND a.actor_id=NEW.owner_id AND a.occurred_at=NEW.created_at
        AND a.payload->>'target_id'=NEW.report_id::text
        AND a.payload->>'workspace_id'=NEW.workspace_id::text
        AND a.payload->>'version'=NEW.version::text) THEN
        RAISE EXCEPTION 'Saved report version requires exact audit' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")
    op.execute("""CREATE FUNCTION protect_saved_report_identity() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP<>'INSERT' THEN
        RAISE EXCEPTION 'Saved report identity is retained' USING ERRCODE='55000';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.organization_id=NEW.organization_id
        AND a.id=NEW.audit_id AND a.aggregate_type='saved_report' AND a.aggregate_id=NEW.report_id
        AND a.type='report.saved_definition.created' AND a.actor_id=NEW.owner_id
        AND a.payload->>'target_id'=NEW.report_id::text
        AND a.payload->>'workspace_id'=NEW.workspace_id::text) THEN
        RAISE EXCEPTION 'Saved report identity requires creation audit' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")
    op.execute("""CREATE FUNCTION protect_saved_report_state() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='TRUNCATE' THEN
        RAISE EXCEPTION 'Saved report state is retained' USING ERRCODE='55000';
      END IF;
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'Saved report state is retained' USING ERRCODE='55000';
      END IF;
      IF TG_OP='INSERT' THEN
        IF NEW.archived OR NOT EXISTS (SELECT 1 FROM saved_report_versions v
          WHERE v.organization_id=NEW.organization_id AND v.report_id=NEW.report_id
          AND v.audit_id=NEW.audit_id) THEN
          RAISE EXCEPTION 'Invalid initial saved report state' USING ERRCODE='23514';
        END IF;
      ELSE
        IF OLD.archived OR NOT EXISTS (SELECT 1 FROM audit_events a
          JOIN saved_report_versions v ON v.organization_id=OLD.organization_id
            AND v.report_id=OLD.report_id AND v.audit_id=OLD.audit_id
          WHERE a.organization_id=NEW.organization_id AND a.id=NEW.audit_id
            AND a.aggregate_type='saved_report' AND a.aggregate_id=NEW.report_id
            AND a.actor_id=v.owner_id AND a.payload->>'target_id'=NEW.report_id::text
            AND a.payload->>'workspace_id'=v.workspace_id::text
            AND ((NOT NEW.archived AND a.type='report.saved_definition.updated'
                  AND a.occurred_at=NEW.updated_at
                  AND a.payload->>'version'=(SELECT max(version)::text FROM saved_report_versions
                    WHERE organization_id=NEW.organization_id AND report_id=NEW.report_id))
              OR (NEW.archived AND a.type='report.saved_definition.archived'
                  AND a.occurred_at=NEW.updated_at
                  AND a.payload->>'version'=(SELECT max(version)::text FROM saved_report_versions
                    WHERE organization_id=NEW.organization_id AND report_id=NEW.report_id)))) THEN
          RAISE EXCEPTION 'Saved report state requires exact audit' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;""")
    op.execute(
        "CREATE TRIGGER protect_saved_report_identities BEFORE INSERT OR UPDATE OR DELETE "
        "ON saved_report_identities FOR EACH ROW "
        "EXECUTE FUNCTION protect_saved_report_identity()"
    )
    op.execute(
        "CREATE TRIGGER protect_saved_report_identities_truncate BEFORE TRUNCATE "
        "ON saved_report_identities FOR EACH STATEMENT "
        "EXECUTE FUNCTION protect_saved_report_identity()"
    )
    op.execute(
        "CREATE TRIGGER protect_saved_report_versions BEFORE INSERT OR UPDATE OR DELETE "
        "ON saved_report_versions FOR EACH ROW "
        "EXECUTE FUNCTION protect_saved_report_version()"
    )
    op.execute(
        "CREATE TRIGGER protect_saved_report_versions_truncate BEFORE TRUNCATE "
        "ON saved_report_versions FOR EACH STATEMENT "
        "EXECUTE FUNCTION protect_saved_report_version()"
    )
    op.execute(
        "CREATE TRIGGER protect_saved_report_states BEFORE INSERT OR UPDATE OR DELETE "
        "ON saved_report_states FOR EACH ROW "
        "EXECUTE FUNCTION protect_saved_report_state()"
    )
    op.execute(
        "CREATE TRIGGER protect_saved_report_states_truncate BEFORE TRUNCATE "
        "ON saved_report_states FOR EACH STATEMENT "
        "EXECUTE FUNCTION protect_saved_report_state()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE saved_report_versions, saved_report_states IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM saved_report_versions)
      OR EXISTS (SELECT 1 FROM saved_report_states) THEN
      RAISE EXCEPTION 'Saved report history prevents rollback; restore a verified backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_table("saved_report_states")
    op.drop_index("ix_saved_report_owner_scope", table_name="saved_report_versions")
    op.drop_table("saved_report_versions")
    op.drop_table("saved_report_identities")
    op.execute("DROP FUNCTION protect_saved_report_state()")
    op.execute("DROP FUNCTION protect_saved_report_version()")
    op.execute("DROP FUNCTION protect_saved_report_identity()")
