"""Require tenant-owned reference sets and unambiguous external IDs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "reference_0002"
down_revision: str | Sequence[str] | None = ("reference_0001", "geography_0002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE bad record;
        BEGIN
          SELECT v.id, v.tenant_id, v.set_code INTO bad
          FROM platform_ref.reference_values v
          WHERE NOT EXISTS (
            SELECT 1 FROM platform_ref.reference_sets s
            WHERE s.tenant_id = v.tenant_id AND s.code = v.set_code
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'reference_0002: value % in tenant % has no set %. Correct before retry',
              bad.id, bad.tenant_id, bad.set_code USING ERRCODE = '23503';
          END IF;
          SELECT tenant_id, set_code, external_id, array_agg(id ORDER BY id) AS ids
            INTO bad
          FROM platform_ref.reference_values WHERE external_id IS NOT NULL
          GROUP BY tenant_id, set_code, external_id HAVING count(*) > 1 LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'reference_0002: duplicate external ID % in tenant % set %, IDs %. Correct first',
              bad.external_id, bad.tenant_id, bad.set_code, bad.ids
              USING ERRCODE = '23505';
          END IF;
        END $$
        """
    )
    op.create_foreign_key(
        "fk_ref_value_tenant_set",
        "reference_values",
        "reference_sets",
        ["tenant_id", "set_code"],
        ["tenant_id", "code"],
        source_schema="platform_ref",
        referent_schema="platform_ref",
    )
    op.create_index(
        "uq_ref_value_tenant_set_external_id",
        "reference_values",
        ["tenant_id", "set_code", "external_id"],
        unique=True,
        schema="platform_ref",
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ref_value_tenant_set_external_id", table_name="reference_values", schema="platform_ref"
    )
    op.drop_constraint(
        "fk_ref_value_tenant_set", "reference_values", schema="platform_ref", type_="foreignkey"
    )
