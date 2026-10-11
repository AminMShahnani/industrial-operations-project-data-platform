"""Index bounded report export worker recovery scans."""

from alembic import op

revision = "a16c3e902bf4"
down_revision = "92e3b0c4a7d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_report_export_recovery",
        "report_export_jobs",
        ["state", "updated_at", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_export_recovery", table_name="report_export_jobs")
