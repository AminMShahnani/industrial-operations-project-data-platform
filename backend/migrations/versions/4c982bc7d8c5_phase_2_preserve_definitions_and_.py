"""Preserve Phase 2 definitions, memberships and department-only grants."""

import sqlalchemy as sa
from alembic import op

revision = "4c982bc7d8c5"
down_revision = "99e791752349"
branch_labels = None
depends_on = None

TABLES = (
    "projects",
    "workspace_groups",
    "group_memberships",
    "project_memberships",
    "department_project_grants",
    "master_data_types",
    "master_data_records",
)
DEFINITIONS = ("projects", "master_data_types", "master_data_records")
MEMBERSHIPS = ("group_memberships", "project_memberships", "department_project_grants")
FK = "fk_department_project_grants_organization_id_workspace_groups"


def upgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM department_project_grants g "
            "JOIN workspace_groups d ON d.organization_id = g.organization_id "
            "AND d.workspace_id = g.workspace_id AND d.id = g.department_id "
            "WHERE d.kind <> 'department')"
        )
    ):
        raise RuntimeError("Invalid team project grants; explicit reviewed repair required")
    op.create_unique_constraint(
        "uq_workspace_groups_scope_kind",
        "workspace_groups",
        ["organization_id", "workspace_id", "id", "kind"],
    )
    op.add_column(
        "department_project_grants",
        sa.Column(
            "department_kind", sa.String(20), nullable=False, server_default=sa.text("'department'")
        ),
    )
    op.create_check_constraint(
        op.f("ck_department_project_grants_department_kind"),
        "department_project_grants",
        "department_kind = 'department'",
    )
    op.drop_constraint(FK, "department_project_grants", type_="foreignkey")
    op.create_foreign_key(
        FK,
        "department_project_grants",
        "workspace_groups",
        ["organization_id", "workspace_id", "department_id", "department_kind"],
        ["organization_id", "workspace_id", "id", "kind"],
    )
    op.execute("""
        CREATE FUNCTION protect_phase2_definition() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'projects' THEN
                IF OLD.lifecycle IS DISTINCT FROM NEW.lifecycle THEN
                    RAISE EXCEPTION 'Project lifecycle definition is immutable'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF TG_TABLE_NAME = 'master_data_types' THEN
                IF (OLD.definition, OLD.id, OLD.owner_id, OLD.organization_id, OLD.workspace_id,
                    OLD.project_id, OLD.scope_id, OLD.scope, OLD.code, OLD.registry, OLD.version)
                   IS DISTINCT FROM
                   (NEW.definition, NEW.id, NEW.owner_id, NEW.organization_id, NEW.workspace_id,
                    NEW.project_id, NEW.scope_id, NEW.scope, NEW.code,
                    NEW.registry, NEW.version) THEN
                    RAISE EXCEPTION 'Master data definition is immutable' USING ERRCODE = '55000';
                END IF;
            ELSE
                IF (OLD.id, OLD.organization_id, OLD.owner_id, OLD.type_id, OLD.code)
                   IS DISTINCT FROM
                   (NEW.id, NEW.organization_id, NEW.owner_id, NEW.type_id, NEW.code) THEN
                    RAISE EXCEPTION 'Master data identity is immutable' USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION protect_phase2_membership() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(OLD) - ARRAY['active', 'revoked'])
               IS DISTINCT FROM (to_jsonb(NEW) - ARRAY['active', 'revoked']) THEN
                RAISE EXCEPTION 'Revoke and replace access grants instead of rewriting history'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION protect_phase2_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Operational history cannot be deleted or truncated'
                USING ERRCODE = '55000';
        END $$
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER preserve_history_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_phase2_history()"
        )
        op.execute(
            f"CREATE TRIGGER preserve_history_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION protect_phase2_history()"
        )
    for table in DEFINITIONS:
        op.execute(
            f"CREATE TRIGGER preserve_definition BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_phase2_definition()"
        )
    for table in MEMBERSHIPS:
        op.execute(
            f"CREATE TRIGGER preserve_membership BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_phase2_membership()"
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")):
            raise RuntimeError(
                "Refusing populated Phase 2 downgrade; restore backup or forward fix"
            )
    for table in TABLES:
        op.execute(f"DROP TRIGGER preserve_history_delete ON {table}")
        op.execute(f"DROP TRIGGER preserve_history_truncate ON {table}")
    for table in DEFINITIONS:
        op.execute(f"DROP TRIGGER preserve_definition ON {table}")
    for table in MEMBERSHIPS:
        op.execute(f"DROP TRIGGER preserve_membership ON {table}")
    for function in (
        "protect_phase2_definition",
        "protect_phase2_membership",
        "protect_phase2_history",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint(FK, "department_project_grants", type_="foreignkey")
    op.create_foreign_key(
        FK,
        "department_project_grants",
        "workspace_groups",
        ["organization_id", "workspace_id", "department_id"],
        ["organization_id", "workspace_id", "id"],
    )
    op.drop_constraint(
        op.f("ck_department_project_grants_department_kind"),
        "department_project_grants",
        type_="check",
    )
    op.drop_column("department_project_grants", "department_kind")
    op.drop_constraint("uq_workspace_groups_scope_kind", "workspace_groups", type_="unique")
