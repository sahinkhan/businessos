"""Record typed Policy authority without guessing legacy principal provenance.

Revision ID: policy_0003
Revises: policy_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "policy_0003"
down_revision: str | Sequence[str] | None = "policy_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_policy"
_TYPES = "('user', 'service_account', 'device')"


def upgrade() -> None:
    op.add_column(
        "subject_role_assignments", sa.Column("subject_type", sa.String(30)), schema=SCHEMA
    )
    op.add_column("delegations", sa.Column("delegator_type", sa.String(30)), schema=SCHEMA)
    op.add_column("delegations", sa.Column("delegatee_type", sa.String(30)), schema=SCHEMA)
    op.create_check_constraint(
        "ck_subject_role_principal_type",
        "subject_role_assignments",
        f"subject_type IS NULL OR subject_type IN {_TYPES}",
        schema=SCHEMA,
    )
    for name in ("delegator_type", "delegatee_type"):
        op.create_check_constraint(
            f"ck_delegation_{name}",
            "delegations",
            f"{name} IS NULL OR {name} IN {_TYPES}",
            schema=SCHEMA,
        )
    op.create_index(
        "ix_policy_typed_subject",
        "subject_role_assignments",
        ["tenant_id", "subject_type", "subject_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_policy_typed_delegatee",
        "delegations",
        ["tenant_id", "delegatee_type", "delegatee_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table, columns in (
        ("subject_role_assignments", "subject_type"),
        ("delegations", "delegator_type, delegatee_type"),
    ):
        if (
            connection.execute(
                sa.text(
                    f"SELECT 1 FROM {SCHEMA}.{table} WHERE "
                    + " OR ".join(f"{column.strip()} IS NOT NULL" for column in columns.split(","))
                    + " LIMIT 1"
                )
            ).first()
            is not None
        ):
            raise RuntimeError("Typed Policy authority requires an operator-reviewed downgrade")
    op.drop_index("ix_policy_typed_delegatee", table_name="delegations", schema=SCHEMA)
    op.drop_index("ix_policy_typed_subject", table_name="subject_role_assignments", schema=SCHEMA)
    for name in ("delegator_type", "delegatee_type"):
        op.drop_constraint(f"ck_delegation_{name}", "delegations", schema=SCHEMA, type_="check")
        op.drop_column("delegations", name, schema=SCHEMA)
    op.drop_constraint(
        "ck_subject_role_principal_type", "subject_role_assignments", schema=SCHEMA, type_="check"
    )
    op.drop_column("subject_role_assignments", "subject_type", schema=SCHEMA)
