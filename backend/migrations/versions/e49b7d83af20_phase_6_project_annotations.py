"""Immutable audited project tags/flags; guarded populated rollback."""

import sqlalchemy as sa
from alembic import op

revision = "e49b7d83af20"
down_revision = "d318af6c902e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_audit_tenant_identity", "audit_events", ["organization_id", "id"]
    )
    op.create_table(
        "project_annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("value", sa.String(60), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_annotations")),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
            name=op.f("fk_project_annotations_organization_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_project_annotations_organization_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "id"],
            ["audit_events.organization_id", "audit_events.id"],
            name=op.f("fk_project_annotations_organization_id_audit_events"),
        ),
        sa.UniqueConstraint(
            "organization_id", "project_id", "kind", "value", name="uq_project_annotation_value"
        ),
        sa.CheckConstraint(
            "kind IN ('tag','flag') AND char_length(value) BETWEEN 1 AND 60 "
            "AND value ~ '^[a-zA-Z0-9_.:-]+$'",
            name=op.f("ck_project_annotations_project_annotation_value"),
        ),
    )
    op.create_index(
        "ix_project_annotations_scope_cursor",
        "project_annotations",
        ["organization_id", "workspace_id", "project_id", "id"],
    )
    op.execute("""CREATE FUNCTION protect_project_annotation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP<>'INSERT' THEN
        RAISE EXCEPTION 'Project annotation history is retained' USING ERRCODE='55000';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.organization_id=NEW.organization_id
        AND a.id=NEW.id AND a.aggregate_type='project' AND a.aggregate_id=NEW.project_id
        AND a.actor_id=NEW.created_by_id AND a.occurred_at=NEW.created_at
        AND a.type='project.' || NEW.kind || '.appended'
        AND a.payload->>'workspace_id'=NEW.workspace_id::text
        AND a.payload->>'project_id'=NEW.project_id::text
        AND a.payload->>'target_id'=NEW.id::text) THEN
        RAISE EXCEPTION 'Project annotation requires exact audit' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;""")
    op.execute(
        "CREATE TRIGGER protect_project_annotations_changes BEFORE INSERT OR UPDATE OR DELETE "
        "ON project_annotations FOR EACH ROW EXECUTE FUNCTION protect_project_annotation()"
    )
    op.execute(
        "CREATE TRIGGER protect_project_annotations_truncate BEFORE TRUNCATE "
        "ON project_annotations "
        "FOR EACH STATEMENT EXECUTE FUNCTION protect_project_annotation()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE project_annotations IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM project_annotations) THEN
      RAISE EXCEPTION 'Retained project annotations prevent rollback; restore a verified backup'
      USING ERRCODE='55000'; END IF; END $$;""")
    op.drop_table("project_annotations")
    op.execute("DROP FUNCTION protect_project_annotation()")
    op.drop_constraint("uq_audit_tenant_identity", "audit_events", type_="unique")
