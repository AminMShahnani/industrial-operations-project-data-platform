"""Add durable private report export jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "92e3b0c4a7d1"
down_revision = "8d77c0f21a46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_export_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("report_digest", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("artifact_key", sa.String(length=500), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_size", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_export_jobs")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_report_export_jobs_org")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_report_export_jobs_workspace"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_report_export_jobs_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "report_id"],
            ["saved_report_identities.organization_id", "saved_report_identities.report_id"],
            name=op.f("fk_report_export_jobs_report"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
            name=op.f("fk_report_export_jobs_project"),
        ),
        sa.CheckConstraint(
            "report_version > 0 AND char_length(report_digest)=64",
            name=op.f("ck_report_export_jobs_version_digest"),
        ),
        sa.CheckConstraint(
            "format IN ('csv','xlsx','pdf')", name=op.f("ck_report_export_jobs_format")
        ),
        sa.CheckConstraint(
            "scope IN ('personal','aggregate')", name=op.f("ck_report_export_jobs_scope")
        ),
        sa.CheckConstraint(
            "state IN ('pending','running','completed','failed','expired','revoked')",
            name=op.f("ck_report_export_jobs_state"),
        ),
    )
    op.create_index(
        "ix_report_export_owner",
        "report_export_jobs",
        ["organization_id", "workspace_id", "owner_id", "created_at"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE report_export_jobs IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM report_export_jobs) THEN
          RAISE EXCEPTION 'Report export job history prevents rollback'
            USING ERRCODE='55000';
        END IF;
        END $$;"""
    )
    op.drop_index("ix_report_export_owner", table_name="report_export_jobs")
    op.drop_table("report_export_jobs")
