"""Phase 5 scoped project review roles.

Revision ID: 71db385e7a02
Revises: 20bfc93ae828
"""

from alembic import op

revision: str = "71db385e7a02"
down_revision: str | None = "20bfc93ae828"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("project_memberships", "department_project_grants"):
        op.drop_constraint(op.f(f"ck_{table}_project_role"), table, type_="check")
        op.create_check_constraint(
            "project_role",
            table,
            "role IN ('ProjectManager', 'Contributor', 'Viewer', 'Reviewer', 'Approver')",
        )


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM project_memberships WHERE role IN ('Reviewer','Approver'))
         OR EXISTS(SELECT 1 FROM department_project_grants WHERE role IN ('Reviewer','Approver'))
      THEN
        RAISE EXCEPTION 'Populated review-role downgrade refused; preserve grants and reconcile'
          USING ERRCODE='55000';
      END IF;
    END $$;
    """)
    for table in ("project_memberships", "department_project_grants"):
        op.drop_constraint(op.f(f"ck_{table}_project_role"), table, type_="check")
        op.create_check_constraint(
            "project_role", table, "role IN ('ProjectManager', 'Contributor', 'Viewer')"
        )
