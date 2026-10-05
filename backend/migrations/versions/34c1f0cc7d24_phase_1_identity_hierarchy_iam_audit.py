"""phase_1_identity_hierarchy_iam_audit"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "34c1f0cc7d24"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_issuer", sa.String(length=500), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=60), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=True),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_tenant_time",
        "audit_events",
        ["organization_id", "occurred_at", "id"],
        unique=False,
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("locale", sa.String(length=35), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("unit_system", sa.String(length=10), nullable=False),
        sa.Column("brand_name", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_table(
        "platform_admins",
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("issuer", "subject", name=op.f("pk_platform_admins")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_users_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_users_organization_id")),
        sa.UniqueConstraint(
            "organization_id", "issuer", "subject", name="uq_users_tenant_identity"
        ),
    )
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_workspaces_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_workspaces_organization_id")),
    )
    op.create_index(
        op.f("ix_workspaces_organization_id"), "workspaces", ["organization_id"], unique=False
    )
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("inherit", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "(scope_type = 'organization' AND scope_id = organization_id AND workspace_id IS NULL) "
            "OR (scope_type = 'workspace' AND workspace_id IS NOT NULL "
            "AND workspace_id = scope_id)",
            name=op.f("ck_grants_grant_scope"),
        ),
        sa.CheckConstraint(
            "NOT inherit OR scope_type = 'organization'", name=op.f("ck_grants_inherit_scope")
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name=op.f("ck_grants_validity_window"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_grants_organization_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_grants_organization_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grants")),
    )
    op.create_index(
        "ix_grants_tenant_user", "grants", ["organization_id", "user_id", "revoked"], unique=False
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("inviter_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "inviter_id"],
            ["users.organization_id", "users.id"],
            name=op.f("fk_invitations_organization_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
            name=op.f("fk_invitations_organization_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_invitations_token_digest")),
    )
    op.create_index(
        op.f("ix_invitations_organization_id"), "invitations", ["organization_id"], unique=False
    )
    op.execute("""
        CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_events is append-only'; END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
    """)
    op.execute("""
        CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation()
    """)


def downgrade() -> None:
    for table in (
        "audit_events",
        "invitations",
        "grants",
        "workspaces",
        "users",
        "platform_admins",
        "organizations",
    ):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")):
            raise RuntimeError(
                "Refusing populated Phase 1 downgrade; restore backup or forward-fix"
            )
    op.drop_index(op.f("ix_invitations_organization_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_grants_tenant_user", table_name="grants")
    op.drop_table("grants")
    op.drop_index(op.f("ix_workspaces_organization_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("platform_admins")
    op.drop_table("organizations")
    op.drop_index("ix_audit_tenant_time", table_name="audit_events")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION reject_audit_mutation()")
