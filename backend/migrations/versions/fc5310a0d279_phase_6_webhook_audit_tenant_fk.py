"""Bind webhook endpoint audit references to the same tenant."""

from alembic import op

revision = "fc5310a0d279"
down_revision = "ee31ac92bf10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_webhook_endpoint_versions_organization_id_audit_events",
        "webhook_endpoint_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_webhook_endpoint_versions_organization_id_audit_events",
        "webhook_endpoint_versions",
        "audit_events",
        ["organization_id", "audit_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_webhook_endpoint_versions_organization_id_audit_events",
        "webhook_endpoint_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_webhook_endpoint_versions_organization_id_audit_events",
        "webhook_endpoint_versions",
        "audit_events",
        ["audit_id"],
        ["id"],
    )
