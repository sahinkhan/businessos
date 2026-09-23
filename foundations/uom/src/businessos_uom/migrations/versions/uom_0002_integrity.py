"""Enforce tenant-owned UoM categories and their declared base units."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "uom_0002"
down_revision: str | Sequence[str] | None = ("uom_0001", "reference_0002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE bad record;
        BEGIN
          SELECT u.id, u.tenant_id, u.category_code INTO bad
          FROM platform_uom.units_of_measure u
          WHERE NOT EXISTS (
            SELECT 1 FROM platform_uom.measurement_categories c
            WHERE c.tenant_id = u.tenant_id AND c.code = u.category_code
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'uom_0002: unit % in tenant % has no category %. Correct ownership before retry',
              bad.id, bad.tenant_id, bad.category_code USING ERRCODE = '23503';
          END IF;
          SELECT u.id, u.tenant_id, u.category_code INTO bad
          FROM platform_uom.units_of_measure u
          JOIN platform_uom.measurement_categories c
            ON c.tenant_id = u.tenant_id AND c.code = u.category_code
          WHERE u.is_base_unit IS DISTINCT FROM (u.code = c.base_unit_code)
             OR (u.is_base_unit AND (u.conversion_ratio <> 1 OR u.conversion_offset <> 0))
          LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'uom_0002: unit % in tenant % category % has invalid base state. Correct first',
              bad.id, bad.tenant_id, bad.category_code USING ERRCODE = '23514';
          END IF;
          SELECT c.id, c.tenant_id, c.code INTO bad
          FROM platform_uom.measurement_categories c
          WHERE EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure u
            WHERE u.tenant_id = c.tenant_id AND u.category_code = c.code
          ) AND NOT EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure u
            WHERE u.tenant_id = c.tenant_id AND u.category_code = c.code
              AND u.code = c.base_unit_code AND u.is_base_unit
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'uom_0002: category % in tenant % lacks its base unit. Correct before retry',
              bad.code, bad.tenant_id USING ERRCODE = '23514';
          END IF;
          SELECT u.id, u.precision INTO bad
          FROM platform_uom.units_of_measure u
          WHERE u.precision > 100 LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'uom_0002: unit % has precision % above the supported 100 decimal places. '
              'Review and normalize the unit before retry',
              bad.id, bad.precision USING ERRCODE = '23514';
          END IF;
          SELECT u.id, u.rounding_mode INTO bad
          FROM platform_uom.units_of_measure u
          WHERE u.rounding_mode NOT IN (
            'ROUND_HALF_UP', 'ROUND_HALF_EVEN', 'ROUND_FLOOR',
            'ROUND_CEILING', 'ROUND_UP', 'ROUND_DOWN'
          ) LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION
              'uom_0002: unit % has unsupported rounding mode %. Correct before retry',
              bad.id, bad.rounding_mode USING ERRCODE = '23514';
          END IF;
        END $$
        """
    )
    op.create_check_constraint(
        "ck_uom_precision_supported",
        "units_of_measure",
        "precision <= 100",
        schema="platform_uom",
    )
    op.create_check_constraint(
        "ck_uom_rounding_mode_supported",
        "units_of_measure",
        "rounding_mode IN ('ROUND_HALF_UP', 'ROUND_HALF_EVEN', 'ROUND_FLOOR', "
        "'ROUND_CEILING', 'ROUND_UP', 'ROUND_DOWN')",
        schema="platform_uom",
    )
    op.create_foreign_key(
        "fk_uom_unit_tenant_category",
        "units_of_measure",
        "measurement_categories",
        ["tenant_id", "category_code"],
        ["tenant_id", "code"],
        source_schema="platform_uom",
        referent_schema="platform_uom",
    )
    op.create_index(
        "uq_uom_one_base_per_category",
        "units_of_measure",
        ["tenant_id", "category_code"],
        unique=True,
        schema="platform_uom",
        postgresql_where=sa.text("is_base_unit"),
    )
    op.execute(
        """
        CREATE FUNCTION platform_uom.enforce_base_unit() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE declared_code text;
        BEGIN
          IF TG_OP = 'UPDATE' AND OLD.is_base_unit AND (
            OLD.tenant_id IS DISTINCT FROM NEW.tenant_id OR
            OLD.category_code IS DISTINCT FROM NEW.category_code OR
            OLD.code IS DISTINCT FROM NEW.code OR
            NEW.is_base_unit IS DISTINCT FROM TRUE
          ) AND EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure u
            WHERE u.tenant_id = OLD.tenant_id AND u.category_code = OLD.category_code
              AND u.id <> OLD.id
          ) THEN
            RAISE EXCEPTION 'UoM base unit cannot move or change while other units exist'
              USING ERRCODE = '23514';
          END IF;
          SELECT c.base_unit_code INTO declared_code
          FROM platform_uom.measurement_categories c
          WHERE c.tenant_id = NEW.tenant_id AND c.code = NEW.category_code
          FOR SHARE;
          IF declared_code IS NULL THEN
            RAISE EXCEPTION 'UoM category is missing for unit %', NEW.id USING ERRCODE = '23503';
          END IF;
          IF NEW.is_base_unit IS DISTINCT FROM (NEW.code = declared_code) THEN
            RAISE EXCEPTION 'UoM unit % conflicts with category base unit %', NEW.id, declared_code
              USING ERRCODE = '23514';
          END IF;
          IF NEW.is_base_unit AND (NEW.conversion_ratio <> 1 OR NEW.conversion_offset <> 0) THEN
            RAISE EXCEPTION 'UoM base unit % must use identity conversion', NEW.id
              USING ERRCODE = '23514';
          END IF;
          IF NOT NEW.is_base_unit AND NOT EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure b
            WHERE b.tenant_id = NEW.tenant_id AND b.category_code = NEW.category_code
              AND b.code = declared_code AND b.is_base_unit
            FOR SHARE OF b
          ) THEN
            RAISE EXCEPTION 'UoM category % requires its base unit first', NEW.category_code
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER units_base_integrity BEFORE INSERT OR UPDATE ON "
        "platform_uom.units_of_measure FOR EACH ROW "
        "EXECUTE FUNCTION platform_uom.enforce_base_unit()"
    )
    op.execute(
        """
        CREATE FUNCTION platform_uom.protect_base_unit_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.is_base_unit AND EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure u
            WHERE u.tenant_id = OLD.tenant_id AND u.category_code = OLD.category_code
              AND u.id <> OLD.id
          ) THEN
            RAISE EXCEPTION 'UoM base unit cannot be deleted while other units exist'
              USING ERRCODE = '23514';
          END IF;
          RETURN OLD;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER units_base_delete BEFORE DELETE ON platform_uom.units_of_measure "
        "FOR EACH ROW EXECUTE FUNCTION platform_uom.protect_base_unit_delete()"
    )
    op.execute(
        """
        CREATE FUNCTION platform_uom.protect_base_category() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.base_unit_code IS DISTINCT FROM OLD.base_unit_code AND EXISTS (
            SELECT 1 FROM platform_uom.units_of_measure u
            WHERE u.tenant_id = OLD.tenant_id AND u.category_code = OLD.code
          ) THEN
            RAISE EXCEPTION 'UoM category base unit cannot change while units exist'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER category_base_integrity BEFORE UPDATE ON "
        "platform_uom.measurement_categories FOR EACH ROW "
        "EXECUTE FUNCTION platform_uom.protect_base_category()"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_uom_precision_supported", "units_of_measure", schema="platform_uom", type_="check"
    )
    op.execute("DROP TRIGGER category_base_integrity ON platform_uom.measurement_categories")
    op.execute("DROP FUNCTION platform_uom.protect_base_category()")
    op.execute("DROP TRIGGER units_base_delete ON platform_uom.units_of_measure")
    op.execute("DROP FUNCTION platform_uom.protect_base_unit_delete()")
    op.execute("DROP TRIGGER units_base_integrity ON platform_uom.units_of_measure")
    op.execute("DROP FUNCTION platform_uom.enforce_base_unit()")
    op.drop_constraint(
        "ck_uom_rounding_mode_supported", "units_of_measure", schema="platform_uom", type_="check"
    )
    op.drop_index(
        "uq_uom_one_base_per_category", table_name="units_of_measure", schema="platform_uom"
    )
    op.drop_constraint(
        "fk_uom_unit_tenant_category", "units_of_measure", schema="platform_uom", type_="foreignkey"
    )
