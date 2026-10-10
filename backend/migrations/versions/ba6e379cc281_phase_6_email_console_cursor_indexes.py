"""Phase 6 email evidence cursor indexes; preserve all retained history."""

from alembic import op

revision = "ba6e379cc281"
down_revision = "5caef6ad5721"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_email_created_cursor", "email_deliveries", ["organization_id", "created_at", "id"]
    )
    op.create_index(
        "ix_email_state_cursor",
        "email_deliveries",
        ["organization_id", "state", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_state_cursor", table_name="email_deliveries")
    op.drop_index("ix_email_created_cursor", table_name="email_deliveries")
