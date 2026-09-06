"""Add structural constraints for persisted migration inventories.

Revision ID: 0004_strict_migration_inventory
Revises: 0003_migration_graph_inventory
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_strict_migration_inventory"
down_revision: str | Sequence[str] | None = "0003_migration_graph_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "installed_module_migrations"
SCHEMA = "platform_module"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_module_migration_inventory_format",
        TABLE,
        "inventory_format IN (1, 2)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_module_migration_inventory_json_arrays",
        TABLE,
        "jsonb_typeof(locations) = 'array' "
        "AND jsonb_typeof(revision_ids) = 'array' "
        "AND jsonb_typeof(revision_manifest) = 'array'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_module_migration_inventory_identity",
        TABLE,
        "btrim(module_id) <> '' AND btrim(module_version) <> '' "
        "AND btrim(migration_namespace) <> ''",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_module_migration_inventory_format_2_nonempty",
        TABLE,
        "inventory_format <> 2 OR "
        "(jsonb_array_length(locations) > 0 "
        "AND jsonb_array_length(revision_ids) > 0 "
        "AND jsonb_array_length(revision_manifest) > 0 "
        "AND btrim(distribution_identity) <> '' "
        "AND distribution_identity <> 'legacy:unknown')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_module_migration_inventory_format_2_nonempty",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_module_migration_inventory_identity",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_module_migration_inventory_json_arrays",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_module_migration_inventory_format",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
