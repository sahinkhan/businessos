"""Enforce consistent geographic parents and address locality."""

from collections.abc import Sequence

from alembic import op

revision: str = "geography_0002"
down_revision: str | Sequence[str] | None = "geography_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE bad record;
        BEGIN
          SELECT city.id, city.country_code INTO bad FROM platform_geo.cities city
          WHERE city.subdivision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM platform_geo.subdivisions sub
            WHERE sub.id = city.subdivision_id AND sub.country_code = city.country_code
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'geography_0002: city % has wrong subdivision in country %. Correct before retry',
              bad.id, bad.country_code USING ERRCODE = '23503';
          END IF;
          SELECT address.id, address.tenant_id INTO bad FROM platform_geo.addresses address
          WHERE address.subdivision_code IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM platform_geo.subdivisions sub
            WHERE sub.country_code = address.country_code AND sub.code = address.subdivision_code
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'geography_0002: address % in tenant % has invalid subdivision. Correct before retry',
              bad.id, bad.tenant_id USING ERRCODE = '23503';
          END IF;
          SELECT address.id, address.tenant_id INTO bad FROM platform_geo.addresses address
          WHERE NOT EXISTS (
            SELECT 1 FROM platform_geo.cities city
            LEFT JOIN platform_geo.subdivisions sub ON sub.id = city.subdivision_id
            WHERE city.country_code = address.country_code AND city.name = address.city
              AND (address.subdivision_code IS NULL OR
                   (sub.country_code = address.country_code
                    AND sub.code = address.subdivision_code))
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'geography_0002: address % in tenant % has wrong city. Correct before retry',
              bad.id, bad.tenant_id USING ERRCODE = '23503';
          END IF;
        END $$
        """
    )
    op.create_unique_constraint(
        "uq_geo_subdivision_id_country",
        "subdivisions",
        ["id", "country_code"],
        schema="platform_geo",
    )
    op.create_unique_constraint(
        "uq_geo_address_tenant_id", "addresses", ["tenant_id", "id"], schema="platform_geo"
    )
    op.create_foreign_key(
        "fk_city_subdivision_country",
        "cities",
        "subdivisions",
        ["subdivision_id", "country_code"],
        ["id", "country_code"],
        source_schema="platform_geo",
        referent_schema="platform_geo",
    )
    op.create_foreign_key(
        "fk_address_subdivision_country",
        "addresses",
        "subdivisions",
        ["country_code", "subdivision_code"],
        ["country_code", "code"],
        source_schema="platform_geo",
        referent_schema="platform_geo",
    )
    op.execute(
        """
        CREATE FUNCTION platform_geo.check_address_city() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM platform_geo.cities city
            LEFT JOIN platform_geo.subdivisions sub ON sub.id = city.subdivision_id
            WHERE city.country_code = NEW.country_code AND city.name = NEW.city
              AND (NEW.subdivision_code IS NULL OR
                   (sub.country_code = NEW.country_code AND sub.code = NEW.subdivision_code))
            FOR SHARE OF city
          ) THEN
            RAISE EXCEPTION 'Address city does not belong to supplied country/subdivision'
              USING ERRCODE = '23503';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER address_city_integrity BEFORE INSERT OR UPDATE ON "
        "platform_geo.addresses FOR EACH ROW EXECUTE FUNCTION platform_geo.check_address_city()"
    )
    op.execute(
        """
        CREATE FUNCTION platform_geo.protect_address_city() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_geo.addresses address
            WHERE address.country_code = OLD.country_code AND address.city = OLD.name
              AND NOT EXISTS (
                SELECT 1 FROM platform_geo.cities city
                LEFT JOIN platform_geo.subdivisions sub ON sub.id = city.subdivision_id
                WHERE city.country_code = address.country_code AND city.name = address.city
                  AND (address.subdivision_code IS NULL OR
                       (sub.country_code = address.country_code
                        AND sub.code = address.subdivision_code))
              )
          ) THEN
            RAISE EXCEPTION 'City change would orphan a tenant address'
              USING ERRCODE = '23503';
          END IF;
          RETURN OLD;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER city_address_update AFTER UPDATE OF name, country_code, subdivision_id "
        "ON platform_geo.cities FOR EACH ROW "
        "EXECUTE FUNCTION platform_geo.protect_address_city()"
    )
    op.execute(
        "CREATE TRIGGER city_address_delete AFTER DELETE ON platform_geo.cities "
        "FOR EACH ROW EXECUTE FUNCTION platform_geo.protect_address_city()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER city_address_delete ON platform_geo.cities")
    op.execute("DROP TRIGGER city_address_update ON platform_geo.cities")
    op.execute("DROP FUNCTION platform_geo.protect_address_city()")
    op.execute("DROP TRIGGER address_city_integrity ON platform_geo.addresses")
    op.execute("DROP FUNCTION platform_geo.check_address_city()")
    op.drop_constraint(
        "fk_address_subdivision_country", "addresses", schema="platform_geo", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_city_subdivision_country", "cities", schema="platform_geo", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_geo_address_tenant_id", "addresses", schema="platform_geo", type_="unique"
    )
    op.drop_constraint(
        "uq_geo_subdivision_id_country", "subdivisions", schema="platform_geo", type_="unique"
    )
