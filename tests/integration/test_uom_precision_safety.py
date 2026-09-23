"""PostgreSQL and public-dispatch proofs for bounded UoM decimal places."""

from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_uom import (
    ConvertedAmountRecord,
    ConvertQuantity,
    CreateMeasurementCategory,
    CreateUnitOfMeasure,
)

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class _AllowAll:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"uom-precision-{tenant_id}",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        ),
    )


@pytest.mark.integration
@pytest.mark.postgres
async def test_precision_29_creation_persistence_and_public_conversion(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    context = _context(tenant_id)
    await app.startup()
    try:
        async with app.container.request_scope() as dependencies:
            await app.runtime.messages.command(
                CreateMeasurementCategory(
                    tenant_id=tenant_id, code="mass", name="Mass", base_unit_code="base"
                ),
                context,
                dependencies,
            )
            await app.runtime.messages.command(
                CreateUnitOfMeasure(
                    tenant_id=tenant_id,
                    category_code="mass",
                    code="base",
                    name="Base",
                    symbol="b",
                    is_base_unit=True,
                ),
                context,
                dependencies,
            )
            await app.runtime.messages.command(
                CreateUnitOfMeasure(
                    tenant_id=tenant_id,
                    category_code="mass",
                    code="fine",
                    name="Fine",
                    symbol="f",
                    precision=29,
                ),
                context,
                dependencies,
            )
            converted = await app.runtime.messages.command(
                ConvertQuantity(
                    tenant_id=tenant_id,
                    from_unit_code="base",
                    to_unit_code="fine",
                    amount=Decimal("1"),
                ),
                context,
                dependencies,
            )
        assert isinstance(converted, ConvertedAmountRecord)
        assert converted.converted_amount == Decimal("1." + "0" * 29)
        assert converted.converted_amount.as_tuple().exponent == -29
        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT precision FROM platform_uom.units_of_measure "
                "WHERE tenant_id = %s AND code = 'fine'",
                (tenant_id,),
            ).fetchone() == (29,)
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE platform_uom.units_of_measure SET precision = 101 "
                    "WHERE tenant_id = %s AND code = 'fine'",
                    (tenant_id,),
                )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_uom_precision_preflight_rejects_dirty_legacy_rows_atomically(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
    )
    assert app.runtime is not None
    migrations = app.runtime.migrations
    migrations.upgrade(postgres_database.migration_url, "uom_0001")
    tenant_id, unit_id = uuid4(), uuid4()
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_uom.measurement_categories "
            "(id, tenant_id, code, name, base_unit_code) "
            "VALUES (%s, %s, 'mass', 'Mass', 'base')",
            (uuid4(), tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_uom.units_of_measure "
            "(id, tenant_id, category_code, code, name, symbol, is_base_unit, precision) "
            "VALUES (%s, %s, 'mass', 'base', 'Base', 'b', true, 101)",
            (unit_id, tenant_id),
        )
        versions_before = connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).fetchall()
        inventory_before = connection.execute(
            "SELECT module_id, revision_manifest FROM platform_module.installed_module_migrations "
            "ORDER BY module_id"
        ).fetchall()
    for _ in range(2):
        with pytest.raises(Exception, match="above the supported 100 decimal places"):
            migrations.upgrade(postgres_database.migration_url, "uom_0002")
        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT precision FROM platform_uom.units_of_measure WHERE id = %s",
                (unit_id,),
            ).fetchone() == (101,)
            assert connection.execute(
                "SELECT to_regclass('platform_uom.units_of_measure')"
            ).fetchone() == ("platform_uom.units_of_measure",)
            assert (
                connection.execute(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                ).fetchall()
                == versions_before
            )
            assert (
                connection.execute(
                    "SELECT module_id, revision_manifest "
                    "FROM platform_module.installed_module_migrations ORDER BY module_id"
                ).fetchall()
                == inventory_before
            )
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "UPDATE platform_uom.units_of_measure SET precision = 100 WHERE id = %s",
            (unit_id,),
        )
    migrations.upgrade(postgres_database.migration_url, "uom_0002")
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT precision FROM platform_uom.units_of_measure WHERE id = %s",
            (unit_id,),
        ).fetchone() == (100,)
