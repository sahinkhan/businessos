"""ADR-012 rollback keeps global masters secure and preserves canonical data."""

from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.version import runtime_version
from tests.conftest import PostgreSQLTestDatabase


def _coordinator() -> MigrationCoordinator:
    registry = ModuleRegistry(platform_version=runtime_version(), sdk_version="0.1.0")
    for module in discover_modules():
        registry.add(module)
    return MigrationCoordinator(registry)


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _currency_state(database: PostgreSQLTestDatabase) -> tuple[list[Any], list[Any], list[Any]]:
    with psycopg.connect(_raw(database.migration_url)) as connection:
        versions = connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).fetchall()
        inventory = connection.execute(
            "SELECT module_id, revision_manifest FROM platform_module.installed_module_migrations "
            "ORDER BY module_id"
        ).fetchall()
        currencies = connection.execute(
            "SELECT id, code, numeric_code, name, minor_unit, source, source_version "
            "FROM platform_currency.currencies ORDER BY code"
        ).fetchall()
    return versions, inventory, currencies


def _assert_global_read_only(
    database: PostgreSQLTestDatabase, subdivision_id: UUID, city_id: UUID
) -> None:
    with psycopg.connect(_raw(database.runtime_url)) as connection:
        for table in ("countries", "subdivisions", "cities"):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert connection.execute(
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    (f"platform_geo.{table}", privilege),
                ).fetchone() == (False,)
            assert connection.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT')",
                (f"platform_geo.{table}",),
            ).fetchone() == (True,)
        assert connection.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT pg_has_role(current_user, 'businessos_migrator', 'MEMBER')"
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT count(*) FROM platform_geo.countries WHERE code = 'XZ'"
        ).fetchone() == (1,)
        attempts = (
            (
                "INSERT INTO platform_geo.countries "
                "(id, code, alpha3_code, numeric_code, name) "
                "VALUES (%s, 'XY', 'XYY', '998', 'Denied')",
                (uuid4(),),
            ),
            (
                "UPDATE platform_geo.subdivisions SET name = 'Denied' WHERE id = %s",
                (subdivision_id,),
            ),
            ("DELETE FROM platform_geo.cities WHERE id = %s", (city_id,)),
        )
        for statement, parameters in attempts:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied:
                connection.execute(statement, parameters)
            assert "platform_geo.addresses" not in str(denied.value)
            connection.rollback()


@pytest.mark.integration
@pytest.mark.postgres
def test_geography_downgrade_keeps_global_tables_read_only_and_addresses_work(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = _coordinator()
    migrations.upgrade(postgres_database.migration_url, "geography_0003")
    subdivision_id, city_id = uuid4(), uuid4()
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries "
            "(id, code, alpha3_code, numeric_code, name, currency_code) "
            "VALUES (%s, 'XZ', 'XZZ', '999', 'Test', 'USD')",
            (uuid4(),),
        )
        connection.execute(
            "INSERT INTO platform_geo.subdivisions "
            "(id, country_code, code, name, category) "
            "VALUES (%s, 'XZ', 'XZ-1', 'Test Region', 'state')",
            (subdivision_id,),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities "
            "(id, country_code, subdivision_id, name) "
            "VALUES (%s, 'XZ', %s, 'Test City')",
            (city_id, subdivision_id),
        )
    _assert_global_read_only(postgres_database, subdivision_id, city_id)

    migrations.downgrade(postgres_database.migration_url, "geography_0002")
    _assert_global_read_only(postgres_database, subdivision_id, city_id)
    tenant_a, tenant_b, address_a, address_b = uuid4(), uuid4(), uuid4(), uuid4()
    with psycopg.connect(_raw(postgres_database.runtime_url)) as connection:
        for tenant_id, address_id in ((tenant_a, address_a), (tenant_b, address_b)):
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            connection.execute(
                "INSERT INTO platform_geo.addresses "
                "(id, tenant_id, country_code, subdivision_code, city, street_line1, "
                "formatted_address) VALUES (%s, %s, 'XZ', 'XZ-1', 'Test City', 'Street', 'Street')",
                (address_id, tenant_id),
            )
            connection.commit()
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_a),))
        assert connection.execute(
            "SELECT id FROM platform_geo.addresses WHERE id = %s", (address_a,)
        ).fetchone() == (address_a,)
        assert (
            connection.execute(
                "SELECT id FROM platform_geo.addresses WHERE id = %s", (address_b,)
            ).fetchone()
            is None
        )

    migrations.upgrade(postgres_database.migration_url, "geography_0003")
    _assert_global_read_only(postgres_database, subdivision_id, city_id)
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT currency_code FROM platform_geo.countries WHERE code = 'XZ'"
        ).fetchone() == ("USD",)
        assert connection.execute("SELECT count(*) FROM platform_geo.addresses").fetchone() == (2,)


@pytest.mark.integration
@pytest.mark.postgres
def test_currency_downgrade_rejects_seeded_data_atomically(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = _coordinator()
    migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries "
            "(id, code, alpha3_code, numeric_code, name, currency_code) "
            "VALUES (%s, 'XZ', 'XZZ', '999', 'Test', 'USD')",
            (uuid4(),),
        )
    before = _currency_state(postgres_database)
    assert len(before[2]) == 42
    for _ in range(2):
        with pytest.raises(Exception, match="currency_0001 downgrade refused") as rejected:
            migrations.downgrade(postgres_database.migration_url)
        assert "forward repair" in str(rejected.value)
        assert "pre-Currency backup" in str(rejected.value)
        assert _currency_state(postgres_database) == before
        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT to_regclass('platform_currency.currencies')"
            ).fetchone() == ("platform_currency.currencies",)
            assert connection.execute(
                "SELECT currency_code FROM platform_geo.countries WHERE code = 'XZ'"
            ).fetchone() == ("USD",)
        migrations.upgrade(postgres_database.migration_url)
        assert _currency_state(postgres_database) == before


@pytest.mark.integration
@pytest.mark.postgres
def test_empty_currency_table_can_downgrade_after_dependents(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = _coordinator()
    migrations.upgrade(postgres_database.migration_url, "currency_0001")
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute("DELETE FROM platform_currency.currencies")
    migrations.downgrade(postgres_database.migration_url)
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT to_regclass('platform_currency.currencies')"
        ).fetchone() == (None,)
    migrations.upgrade(postgres_database.migration_url, "currency_0001")
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_currency.currencies"
        ).fetchone() == (42,)
