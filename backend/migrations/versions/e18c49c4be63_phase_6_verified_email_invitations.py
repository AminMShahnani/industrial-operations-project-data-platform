"""Phase 6 verified-email invitation lifecycle, preserving bearer invitations."""

import sqlalchemy as sa
from alembic import op

revision = "e18c49c4be63"
down_revision = "34e34c3ce85a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column("acceptance_mode", sa.String(20), nullable=False, server_default="token"),
    )
    op.alter_column("invitations", "token_digest", existing_type=sa.String(64), nullable=True)
    op.create_check_constraint(
        op.f("ck_invitations_ck_invitation_acceptance_credentials"),
        "invitations",
        "(acceptance_mode = 'token' AND token_digest IS NOT NULL) OR "
        "(acceptance_mode = 'verified_email' AND token_digest IS NULL)",
    )
    op.execute("""
        CREATE FUNCTION guard_invitation_binding() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'UPDATE' THEN
            RAISE EXCEPTION 'Invitation history cannot be removed';
          END IF;
          IF (to_jsonb(NEW) - 'accepted_at') IS DISTINCT FROM
             (to_jsonb(OLD) - 'accepted_at') OR
             (OLD.accepted_at IS NOT NULL AND
              NEW.accepted_at IS DISTINCT FROM OLD.accepted_at) THEN
            RAISE EXCEPTION 'Invitation binding and acceptance are immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_invitation_binding
          BEFORE UPDATE OR DELETE ON invitations
          FOR EACH ROW EXECUTE FUNCTION guard_invitation_binding();
        CREATE TRIGGER guard_invitation_truncate
          BEFORE TRUNCATE ON invitations
          FOR EACH STATEMENT EXECUTE FUNCTION guard_invitation_binding();
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM invitations WHERE acceptance_mode <> 'token')")
    ):
        raise RuntimeError(
            "Verified-email invitation history exists; forward fix or restore required"
        )
    op.execute("DROP TRIGGER guard_invitation_truncate ON invitations")
    op.execute("DROP TRIGGER guard_invitation_binding ON invitations")
    op.execute("DROP FUNCTION guard_invitation_binding()")
    op.drop_constraint(
        op.f("ck_invitations_ck_invitation_acceptance_credentials"), "invitations", type_="check"
    )
    op.alter_column("invitations", "token_digest", existing_type=sa.String(64), nullable=False)
    op.drop_column("invitations", "acceptance_mode")
