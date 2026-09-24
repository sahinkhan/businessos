"""Expand support authority with typed principal provenance.

Revision ID: policy_0004
Revises: policy_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "policy_0004"
down_revision: str | Sequence[str] | None = "policy_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_policy"
TABLE = "support_access_grants"
TYPES = "('user', 'service_account', 'device')"


def upgrade() -> None:
    for name in ("support_principal_type", "approved_by_type"):
        op.add_column(TABLE, sa.Column(name, sa.String(30), nullable=True), schema=SCHEMA)
        op.create_check_constraint(
            f"ck_support_access_{name}",
            TABLE,
            f"{name} IS NULL OR {name} IN {TYPES}",
            schema=SCHEMA,
        )
    op.create_index(
        "ix_support_access_typed_live",
        TABLE,
        ["tenant_id", "support_principal_type", "support_principal_id", "valid_to"],
        schema=SCHEMA,
    )
    for name, table, columns in (
        (
            "ix_policy_v2_role_permission",
            "role_permissions",
            ["tenant_id", "role_id", "permission_code"],
        ),
        (
            "ix_policy_v2_record_policy",
            "record_policies",
            ["tenant_id", "resource_type", "role_id"],
        ),
        (
            "ix_policy_v2_field_policy",
            "field_policies",
            ["tenant_id", "resource_type", "field_name"],
        ),
        ("ix_policy_v2_approval_limit", "approval_limits", ["tenant_id", "action_type", "role_id"]),
        ("ix_policy_v2_delegator", "delegations", ["tenant_id", "delegator_type", "delegator_id"]),
    ):
        op.create_index(name, table, columns, schema=SCHEMA)


def downgrade() -> None:
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text(
                f"SELECT 1 FROM {SCHEMA}.{TABLE} WHERE "
                "support_principal_type IS NOT NULL OR approved_by_type IS NOT NULL LIMIT 1"
            )
        ).first()
        is not None
    ):
        raise RuntimeError("Typed support access requires an operator-reviewed downgrade")
    op.drop_index("ix_support_access_typed_live", table_name=TABLE, schema=SCHEMA)
    for name, table in (
        ("ix_policy_v2_delegator", "delegations"),
        ("ix_policy_v2_approval_limit", "approval_limits"),
        ("ix_policy_v2_field_policy", "field_policies"),
        ("ix_policy_v2_record_policy", "record_policies"),
        ("ix_policy_v2_role_permission", "role_permissions"),
    ):
        op.drop_index(name, table_name=table, schema=SCHEMA)
    for name in ("approved_by_type", "support_principal_type"):
        op.drop_constraint(f"ck_support_access_{name}", TABLE, schema=SCHEMA, type_="check")
        op.drop_column(TABLE, name, schema=SCHEMA)
