"""Enforce tenant ownership of Party children and address assignments."""

from collections.abc import Sequence

from alembic import op

revision: str = "party_0002"
down_revision: str | Sequence[str] | None = ("party_0001", "uom_0002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARTY_LINKS = (
    ("person_profiles", "party_id"),
    ("organization_profiles", "party_id"),
    ("party_relationships", "from_party_id"),
    ("party_relationships", "to_party_id"),
    ("contact_points", "party_id"),
    ("party_address_assignments", "party_id"),
    ("external_identifiers", "party_id"),
)


def upgrade() -> None:
    for table, column in _PARTY_LINKS:
        op.execute(
            f"""
            DO $$
            DECLARE bad record;
            BEGIN
              SELECT child.id, child.tenant_id INTO bad
              FROM platform_party.{table} child
              WHERE NOT EXISTS (
                SELECT 1 FROM platform_party.parties parent
                WHERE parent.id = child.{column} AND parent.tenant_id = child.tenant_id
              ) LIMIT 1;
              IF FOUND THEN
                RAISE EXCEPTION
                  'party_0002: {table} row % in tenant % has wrong {column}. Correct before retry',
                  bad.id, bad.tenant_id USING ERRCODE = '23503';
              END IF;
            END $$
            """
        )
    op.execute(
        """
        DO $$
        DECLARE bad record;
        BEGIN
          SELECT link.id, link.tenant_id INTO bad
          FROM platform_party.party_address_assignments link
          WHERE NOT EXISTS (
            SELECT 1 FROM platform_geo.addresses address
            WHERE address.id = link.address_id AND address.tenant_id = link.tenant_id
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'party_0002: assignment % in tenant % has wrong address. Correct before retry',
              bad.id, bad.tenant_id USING ERRCODE = '23503';
          END IF;
        END $$
        """
    )
    op.create_unique_constraint(
        "uq_party_tenant_id", "parties", ["tenant_id", "id"], schema="platform_party"
    )
    for table, column in _PARTY_LINKS:
        op.create_foreign_key(
            f"fk_{table}_{column}_tenant",
            table,
            "parties",
            ["tenant_id", column],
            ["tenant_id", "id"],
            source_schema="platform_party",
            referent_schema="platform_party",
        )
    op.create_foreign_key(
        "fk_party_address_tenant",
        "party_address_assignments",
        "addresses",
        ["tenant_id", "address_id"],
        ["tenant_id", "id"],
        source_schema="platform_party",
        referent_schema="platform_geo",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_party_address_tenant",
        "party_address_assignments",
        schema="platform_party",
        type_="foreignkey",
    )
    for table, column in reversed(_PARTY_LINKS):
        op.drop_constraint(
            f"fk_{table}_{column}_tenant", table, schema="platform_party", type_="foreignkey"
        )
    op.drop_constraint("uq_party_tenant_id", "parties", schema="platform_party", type_="unique")
