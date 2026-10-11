"""Store organization-scoped Domain Pack installation and release provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2ad7f8e6c301"
down_revision = "a16c3e902bf4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_pack_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.String(180), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("installed_by", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_pack_installations")),
        sa.UniqueConstraint("organization_id", "id", name="uq_domain_pack_installation_tenant"),
        sa.UniqueConstraint("organization_id", "pack_id", name="uq_domain_pack_installation_id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "installed_by"], ["users.organization_id", "users.id"]
        ),
        sa.CheckConstraint(
            "row_version >= 1", name="ck_domain_pack_installations_row_version_positive"
        ),
        sa.CheckConstraint(
            "state IN ('installed', 'enabled', 'disabled', 'uninstalled')",
            name="ck_domain_pack_installations_state_valid",
        ),
    )
    op.create_table(
        "domain_pack_provenance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.String(180), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_pack_provenance")),
        sa.UniqueConstraint(
            "organization_id",
            "installation_id",
            "version",
            name="uq_domain_pack_provenance_release",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "installation_id"],
            ["domain_pack_installations.organization_id", "domain_pack_installations.id"],
        ),
        sa.CheckConstraint(
            "jsonb_typeof(artifacts) = 'array'", name="ck_domain_pack_provenance_artifacts_array"
        ),
    )
    op.create_index(
        "ix_domain_pack_installations_org_state",
        "domain_pack_installations",
        ["organization_id", "state"],
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE domain_pack_installations, domain_pack_provenance IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM domain_pack_installations)
          OR EXISTS (SELECT 1 FROM domain_pack_provenance) THEN
          RAISE EXCEPTION 'Pack history prevents rollback; restore a verified backup'
          USING ERRCODE='55000';
        END IF;
        END $$;"""
    )
    op.drop_index("ix_domain_pack_installations_org_state", table_name="domain_pack_installations")
    op.drop_table("domain_pack_provenance")
    op.drop_table("domain_pack_installations")
