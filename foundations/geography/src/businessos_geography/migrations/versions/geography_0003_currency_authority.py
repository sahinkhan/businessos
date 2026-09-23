"""Link countries to Currency and make global geography runtime read-only."""

from collections.abc import Sequence

from alembic import op

revision: str = "geography_0003"
down_revision: str | Sequence[str] | None = ("geography_0002", "currency_0001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE bad record;
        BEGIN
          SELECT country.code, country.currency_code INTO bad
          FROM platform_geo.countries country
          WHERE country.currency_code IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM platform_currency.currencies currency
            WHERE currency.code = country.currency_code
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'geography_0003: country % references unknown currency %. Correct before retry',
              bad.code, bad.currency_code USING ERRCODE = '23503';
          END IF;
        END $$
        """
    )
    op.create_foreign_key(
        "fk_country_currency",
        "countries",
        "currencies",
        ["currency_code"],
        ["code"],
        source_schema="platform_geo",
        referent_schema="platform_currency",
    )
    for table in ("countries", "subdivisions", "cities"):
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform_geo.{table} FROM businessos_app"
        )
        op.execute(f"GRANT SELECT ON platform_geo.{table} TO businessos_app")
    # geography_0002 used FOR SHARE while runtime still had global UPDATE. A row
    # lock requires UPDATE privilege, so the read-only runtime variant omits it.
    # Trusted catalogue writers remain serialized by the migration process.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_geo.check_address_city() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM platform_geo.cities city
            LEFT JOIN platform_geo.subdivisions sub ON sub.id = city.subdivision_id
            WHERE city.country_code = NEW.country_code AND city.name = NEW.city
              AND (NEW.subdivision_code IS NULL OR
                   (sub.country_code = NEW.country_code AND sub.code = NEW.subdivision_code))
          ) THEN
            RAISE EXCEPTION 'Address city does not belong to supplied country/subdivision'
              USING ERRCODE = '23503';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON platform_geo.addresses TO businessos_app")


def downgrade() -> None:
    op.drop_constraint(
        "fk_country_currency", "countries", schema="platform_geo", type_="foreignkey"
    )
    # The Currency FK can be reversed, but ADR-012's canonical-master privilege
    # boundary cannot. Keep the read-only address trigger as well: the older
    # FOR SHARE variant requires global UPDATE privilege for tenant address writes.
    for table in ("countries", "subdivisions", "cities"):
        op.execute(f"REVOKE ALL PRIVILEGES ON platform_geo.{table} FROM businessos_app")
        op.execute(f"GRANT SELECT ON platform_geo.{table} TO businessos_app")
