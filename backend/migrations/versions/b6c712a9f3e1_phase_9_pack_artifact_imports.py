"""Persist idempotent, scoped Domain Pack artifact import provenance."""

import sqlalchemy as sa
from alembic import op

revision = "b6c712a9f3e1"
down_revision = "2ad7f8e6c301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_pack_artifact_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.String(180), nullable=False),
        sa.Column("pack_version", sa.String(128), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.String(120), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("artifact_kind", sa.String(40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("imported_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_pack_artifact_imports")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_domain_pack_import_key"),
        sa.ForeignKeyConstraint(
            ["organization_id", "pack_id"],
            ["domain_pack_installations.organization_id", "domain_pack_installations.pack_id"],
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"], ["workspaces.organization_id", "workspaces.id"]
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "project_id"],
            ["projects.organization_id", "projects.workspace_id", "projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "imported_by"], ["users.organization_id", "users.id"]
        ),
        sa.CheckConstraint("artifact_version >= 1", name="ck_domain_pack_import_artifact_version"),
        sa.CheckConstraint("char_length(package_sha256) = 64", name="ck_domain_pack_import_digest"),
    )
    op.create_index(
        "ix_domain_pack_import_target",
        "domain_pack_artifact_imports",
        ["organization_id", "workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE domain_pack_artifact_imports IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM domain_pack_artifact_imports) THEN
          RAISE EXCEPTION 'Pack import history prevents rollback; restore a verified backup'
          USING ERRCODE='55000';
        END IF;
        END $$;"""
    )
    op.drop_index("ix_domain_pack_import_target", table_name="domain_pack_artifact_imports")
    op.drop_table("domain_pack_artifact_imports")
