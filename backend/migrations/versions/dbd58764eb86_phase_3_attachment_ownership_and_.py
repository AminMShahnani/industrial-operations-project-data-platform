"""Phase 3 attachment ownership and indexed lookups."""

import sqlalchemy as sa
from alembic import op

revision = "dbd58764eb86"
down_revision = "464245e2e729"
branch_labels = None
depends_on = None
FK = "fk_files_organization_id_submissions"


def upgrade() -> None:
    invalid = op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM files f JOIN submissions s
          ON (f.organization_id, f.workspace_id, f.submission_id) =
             (s.organization_id, s.workspace_id, s.id)
          WHERE f.owner_id <> s.owner_id)
    """)
    )
    if invalid:
        raise RuntimeError("Invalid attachment ownership; investigate without rewriting history")
    op.create_unique_constraint(
        "uq_submissions_scope_owner",
        "submissions",
        ["organization_id", "workspace_id", "id", "owner_id"],
    )
    op.drop_constraint(FK, "files", type_="foreignkey")
    op.create_foreign_key(
        FK,
        "files",
        "submissions",
        ["organization_id", "workspace_id", "submission_id", "owner_id"],
        ["organization_id", "workspace_id", "id", "owner_id"],
    )
    op.create_index(
        "ix_submissions_scope_state_cursor",
        "submissions",
        ["organization_id", "workspace_id", "form_id", "state", "id"],
    )
    op.create_index(
        "ix_users_scope_email_active", "users", ["organization_id", "email", "active", "id"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM files LIMIT 1)")):
        raise RuntimeError("Refusing populated attachment ownership downgrade; retain schema")
    op.drop_constraint(FK, "files", type_="foreignkey")
    op.drop_constraint("uq_submissions_scope_owner", "submissions", type_="unique")
    op.create_foreign_key(
        FK,
        "files",
        "submissions",
        ["organization_id", "workspace_id", "submission_id"],
        ["organization_id", "workspace_id", "id"],
    )
    op.drop_index("ix_submissions_scope_state_cursor", table_name="submissions")
    op.drop_index("ix_users_scope_email_active", table_name="users")
