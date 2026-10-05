"""Empty production baseline; business schemas begin in their owning phases.

Rollback removes only the Alembic revision marker. No operational data exists here.
"""

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
