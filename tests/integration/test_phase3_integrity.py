"""PostgreSQL checks for the Phase 3 forward integrity revisions."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_geography import AddressRecord, SubdivisionRecord
from businessos_party import PartyRecord

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


def _foundation_modules() -> tuple[Any, ...]:
    return tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )


class _AllowAll:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"phase3-{tenant_id}",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        ),
    )


async def _command(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(message, context, dependencies)


@pytest.mark.integration
@pytest.mark.postgres
async def test_phase3_commands_enforce_parent_and_tenant_integrity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    from businessos_geography import (
        CreateAddress,
        RegisterCity,
        RegisterCountry,
        RegisterSubdivision,
    )
    from businessos_party import (
        AddContactPoint,
        AddExternalIdentifier,
        AssignPartyAddress,
        CreatePersonParty,
    )
    from businessos_reference_data import CreateReferenceValue, RegisterReferenceSet
    from businessos_uom import CreateMeasurementCategory, CreateUnitOfMeasure

    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_a, tenant_b = uuid4(), uuid4()
    a, b = _context(tenant_a), _context(tenant_b)
    await app.startup()
    try:
        await _command(
            app, RegisterCountry(code="AA", alpha3_code="AAA", numeric_code="001", name="A"), a
        )
        await _command(
            app, RegisterCountry(code="BB", alpha3_code="BBB", numeric_code="002", name="B"), a
        )
        sub_a = await _command(
            app, RegisterSubdivision(country_code="AA", code="AA-1", name="A1", category="state"), a
        )
        sub_b = await _command(
            app, RegisterSubdivision(country_code="BB", code="BB-1", name="B1", category="state"), a
        )
        assert isinstance(sub_a, SubdivisionRecord)
        assert isinstance(sub_b, SubdivisionRecord)
        await _command(
            app, RegisterCity(country_code="AA", name="Acity", subdivision_id=sub_a.id), a
        )
        with pytest.raises(BusinessOSError):
            await _command(
                app, RegisterCity(country_code="AA", name="Wrong", subdivision_id=sub_b.id), a
            )
        address_a = await _command(
            app,
            CreateAddress(
                tenant_id=tenant_a,
                country_code="AA",
                subdivision_code="AA-1",
                city="Acity",
                street_line1="1 A",
            ),
            a,
        )
        address_b = await _command(
            app,
            CreateAddress(
                tenant_id=tenant_b,
                country_code="AA",
                subdivision_code="AA-1",
                city="Acity",
                street_line1="1 B",
            ),
            b,
        )
        assert isinstance(address_a, AddressRecord)
        assert isinstance(address_b, AddressRecord)
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                CreateAddress(
                    tenant_id=tenant_a,
                    country_code="AA",
                    subdivision_code="BB-1",
                    city="Acity",
                    street_line1="X",
                ),
                a,
            )
        party_a = await _command(
            app, CreatePersonParty(tenant_id=tenant_a, first_name="A", last_name="One"), a
        )
        party_b = await _command(
            app, CreatePersonParty(tenant_id=tenant_b, first_name="B", last_name="Two"), b
        )
        assert isinstance(party_a, PartyRecord)
        assert isinstance(party_b, PartyRecord)
        await _command(
            app,
            AssignPartyAddress(tenant_id=tenant_a, party_id=party_a.id, address_id=address_a.id),
            a,
        )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                AssignPartyAddress(
                    tenant_id=tenant_a, party_id=party_a.id, address_id=address_b.id
                ),
                a,
            )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                AddContactPoint(
                    tenant_id=tenant_a,
                    party_id=party_b.id,
                    channel_type="email",
                    value="a@example.test",
                ),
                a,
            )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                AddExternalIdentifier(
                    tenant_id=tenant_a, party_id=party_b.id, provider="test", identifier_value="x"
                ),
                a,
            )
        await _command(
            app,
            RegisterReferenceSet(
                tenant_id=tenant_a, code="colors", name="Colors", owning_module="test"
            ),
            a,
        )
        await _command(
            app,
            CreateReferenceValue(
                tenant_id=tenant_a,
                set_code="colors",
                code="red",
                label_key="red",
                default_label="Red",
                external_id="ext",
            ),
            a,
        )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                CreateReferenceValue(
                    tenant_id=tenant_a,
                    set_code="missing",
                    code="x",
                    label_key="x",
                    default_label="X",
                ),
                a,
            )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                CreateReferenceValue(
                    tenant_id=tenant_a,
                    set_code="colors",
                    code="blue",
                    label_key="blue",
                    default_label="Blue",
                    external_id="ext",
                ),
                a,
            )
        await _command(
            app,
            CreateMeasurementCategory(
                tenant_id=tenant_a, code="length", name="Length", base_unit_code="m"
            ),
            a,
        )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                CreateUnitOfMeasure(
                    tenant_id=tenant_b,
                    category_code="length",
                    code="m",
                    name="Meter",
                    symbol="m",
                    is_base_unit=True,
                ),
                b,
            )
        await _command(
            app,
            CreateUnitOfMeasure(
                tenant_id=tenant_a,
                category_code="length",
                code="m",
                name="Meter",
                symbol="m",
                is_base_unit=True,
            ),
            a,
        )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                CreateUnitOfMeasure(
                    tenant_id=tenant_a,
                    category_code="length",
                    code="cm",
                    name="Centimeter",
                    symbol="cm",
                    is_base_unit=True,
                    conversion_ratio=Decimal("0.01"),
                ),
                a,
            )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_phase3_database_constraints_reject_cross_tenant_and_orphans(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_a, tenant_b, party_b = uuid4(), uuid4(), uuid4()
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO platform_party.parties "
            "(id, tenant_id, party_number, party_type, display_name) "
            "VALUES (%s, %s, 'B1', 'person', 'B')",
            (party_b, tenant_b),
        )
        connection.commit()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_party.contact_points "
                "(id, tenant_id, party_id, channel_type, value) "
                "VALUES (%s, %s, %s, 'email', 'x')",
                (uuid4(), tenant_a, party_b),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_ref.reference_values "
                "(id, tenant_id, set_code, code, label_key, default_label) "
                "VALUES (%s, %s, 'missing', 'x', 'x', 'X')",
                (uuid4(), tenant_a),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_uom.units_of_measure "
                "(id, tenant_id, category_code, code, name, symbol) "
                "VALUES (%s, %s, 'missing', 'm', 'Meter', 'm')",
                (uuid4(), tenant_a),
            )
        connection.rollback()
        connection.execute(
            "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
            "VALUES (%s, 'AA', 'AAA', '001', 'A'), (%s, 'BB', 'BBB', '002', 'B')",
            (uuid4(), uuid4()),
        )
        sub_b = uuid4()
        connection.execute(
            "INSERT INTO platform_geo.subdivisions (id, country_code, code, name, category) "
            "VALUES (%s, 'BB', 'BB-1', 'B1', 'state')",
            (sub_b,),
        )
        party_a, address_b = uuid4(), uuid4()
        connection.execute(
            "INSERT INTO platform_party.parties "
            "(id, tenant_id, party_number, party_type, display_name) "
            "VALUES (%s, %s, 'A1', 'person', 'A')",
            (party_a, tenant_a),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities (id, country_code, name) VALUES (%s, 'BB', 'Bcity')",
            (uuid4(),),
        )
        connection.execute(
            "INSERT INTO platform_geo.addresses "
            "(id, tenant_id, country_code, city, street_line1, formatted_address) "
            "VALUES (%s, %s, 'BB', 'Bcity', '1 B', '1 B')",
            (address_b, tenant_b),
        )
        connection.execute(
            "INSERT INTO platform_ref.reference_sets "
            "(id, tenant_id, code, name, owning_module) "
            "VALUES (%s, %s, 'colors', 'Colors', 'test')",
            (uuid4(), tenant_a),
        )
        connection.execute(
            "INSERT INTO platform_ref.reference_values "
            "(id, tenant_id, set_code, code, label_key, default_label, external_id) "
            "VALUES (%s, %s, 'colors', 'red', 'red', 'Red', 'ext')",
            (uuid4(), tenant_a),
        )
        connection.execute(
            "INSERT INTO platform_uom.measurement_categories "
            "(id, tenant_id, code, name, base_unit_code) "
            "VALUES (%s, %s, 'length', 'Length', 'm')",
            (uuid4(), tenant_a),
        )
        connection.execute(
            "INSERT INTO platform_uom.units_of_measure "
            "(id, tenant_id, category_code, code, name, symbol, is_base_unit) "
            "VALUES (%s, %s, 'length', 'm', 'Meter', 'm', true)",
            (uuid4(), tenant_a),
        )
        connection.commit()

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_party.party_address_assignments "
                "(id, tenant_id, party_id, address_id) VALUES (%s, %s, %s, %s)",
                (uuid4(), tenant_a, party_a, address_b),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_geo.cities (id, country_code, subdivision_id, name) "
                "VALUES (%s, 'AA', %s, 'Wrong')",
                (uuid4(), sub_b),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_geo.addresses "
                "(id, tenant_id, country_code, subdivision_code, city, street_line1, "
                "formatted_address) VALUES (%s, %s, 'AA', 'BB-1', 'Bcity', 'X', 'X')",
                (uuid4(), tenant_a),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO platform_ref.reference_values "
                "(id, tenant_id, set_code, code, label_key, default_label, external_id) "
                "VALUES (%s, %s, 'colors', 'blue', 'blue', 'Blue', 'ext')",
                (uuid4(), tenant_a),
            )
        connection.rollback()
        connection.execute(
            "INSERT INTO platform_ref.reference_values "
            "(id, tenant_id, set_code, code, label_key, default_label) "
            "VALUES (%s, %s, 'colors', 'none1', 'none1', 'None 1'), "
            "(%s, %s, 'colors', 'none2', 'none2', 'None 2')",
            (uuid4(), tenant_a, uuid4(), tenant_a),
        )
        assert connection.execute(
            "SELECT count(*) FROM platform_ref.reference_values "
            "WHERE tenant_id = %s AND set_code = 'colors' AND external_id IS NULL",
            (tenant_a,),
        ).fetchone() == (2,)
        connection.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO platform_uom.units_of_measure "
                "(id, tenant_id, category_code, code, name, symbol, is_base_unit) "
                "VALUES (%s, %s, 'length', 'cm', 'Centimeter', 'cm', true)",
                (uuid4(), tenant_a),
            )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize(
    ("kind", "old_revision", "new_revision"),
    (
        ("geography", "geography_0001", "geography_0002"),
        ("geography_address", "geography_0001", "geography_0002"),
        ("reference", "reference_0001", "reference_0002"),
        ("reference_external", "reference_0001", "reference_0002"),
        ("uom", "uom_0001", "uom_0002"),
        ("uom_base", "uom_0001", "uom_0002"),
        ("party", "party_0001", "party_0002"),
        ("party_address", "party_0001", "party_0002"),
    ),
)
def test_phase3_dirty_data_preflight_preserves_and_retries(
    postgres_database: PostgreSQLTestDatabase,
    kind: str,
    old_revision: str,
    new_revision: str,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    migrations = app.runtime.migrations
    migrations.upgrade(postgres_database.migration_url, old_revision)
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    row_id, tenant_a, tenant_b = uuid4(), uuid4(), uuid4()
    with psycopg.connect(url) as connection:
        if kind == "geography":
            sub_id = uuid4()
            connection.execute(
                "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
                "VALUES (%s, 'AA', 'AAA', '001', 'A'), (%s, 'BB', 'BBB', '002', 'B')",
                (uuid4(), uuid4()),
            )
            connection.execute(
                "INSERT INTO platform_geo.subdivisions "
                "(id, country_code, code, name, category) "
                "VALUES (%s, 'BB', 'BB-1', 'B1', 'state')",
                (sub_id,),
            )
            connection.execute(
                "INSERT INTO platform_geo.cities (id, country_code, subdivision_id, name) "
                "VALUES (%s, 'AA', %s, 'Wrong')",
                (row_id, sub_id),
            )
        elif kind == "geography_address":
            connection.execute(
                "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
                "VALUES (%s, 'AA', 'AAA', '001', 'A'), (%s, 'BB', 'BBB', '002', 'B')",
                (uuid4(), uuid4()),
            )
            connection.execute(
                "INSERT INTO platform_geo.subdivisions "
                "(id, country_code, code, name, category) "
                "VALUES (%s, 'BB', 'BB-1', 'B1', 'state')",
                (uuid4(),),
            )
            connection.execute(
                "INSERT INTO platform_geo.cities (id, country_code, name) "
                "VALUES (%s, 'AA', 'Acity')",
                (uuid4(),),
            )
            connection.execute(
                "INSERT INTO platform_geo.addresses "
                "(id, tenant_id, country_code, subdivision_code, city, street_line1, "
                "formatted_address) VALUES (%s, %s, 'AA', 'BB-1', 'Acity', 'X', 'X')",
                (row_id, tenant_a),
            )
        elif kind == "reference":
            connection.execute(
                "INSERT INTO platform_ref.reference_values "
                "(id, tenant_id, set_code, code, label_key, default_label) "
                "VALUES (%s, %s, 'missing', 'x', 'x', 'X')",
                (row_id, tenant_a),
            )
        elif kind == "reference_external":
            connection.execute(
                "INSERT INTO platform_ref.reference_sets "
                "(id, tenant_id, code, name, owning_module) "
                "VALUES (%s, %s, 'colors', 'Colors', 'test')",
                (uuid4(), tenant_a),
            )
            connection.execute(
                "INSERT INTO platform_ref.reference_values "
                "(id, tenant_id, set_code, code, label_key, default_label, external_id) "
                "VALUES (%s, %s, 'colors', 'red', 'red', 'Red', 'ext'), "
                "(%s, %s, 'colors', 'blue', 'blue', 'Blue', 'ext')",
                (uuid4(), tenant_a, row_id, tenant_a),
            )
        elif kind == "uom":
            connection.execute(
                "INSERT INTO platform_uom.units_of_measure "
                "(id, tenant_id, category_code, code, name, symbol, is_base_unit) "
                "VALUES (%s, %s, 'length', 'm', 'Meter', 'm', true)",
                (row_id, tenant_a),
            )
        elif kind == "uom_base":
            connection.execute(
                "INSERT INTO platform_uom.measurement_categories "
                "(id, tenant_id, code, name, base_unit_code) "
                "VALUES (%s, %s, 'length', 'Length', 'm')",
                (uuid4(), tenant_a),
            )
            connection.execute(
                "INSERT INTO platform_uom.units_of_measure "
                "(id, tenant_id, category_code, code, name, symbol, is_base_unit) "
                "VALUES (%s, %s, 'length', 'm', 'Meter', 'm', true), "
                "(%s, %s, 'length', 'cm', 'Centimeter', 'cm', true)",
                (uuid4(), tenant_a, row_id, tenant_a),
            )
        elif kind == "party":
            parent_id = uuid4()
            connection.execute(
                "INSERT INTO platform_party.parties "
                "(id, tenant_id, party_number, party_type, display_name) "
                "VALUES (%s, %s, 'P1', 'person', 'Parent')",
                (parent_id, tenant_b),
            )
            connection.execute(
                "INSERT INTO platform_party.contact_points "
                "(id, tenant_id, party_id, channel_type, value) "
                "VALUES (%s, %s, %s, 'email', 'x')",
                (row_id, tenant_a, parent_id),
            )
        else:
            party_id, address_id = uuid4(), uuid4()
            connection.execute(
                "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
                "VALUES (%s, 'AA', 'AAA', '001', 'A')",
                (uuid4(),),
            )
            connection.execute(
                "INSERT INTO platform_geo.cities (id, country_code, name) "
                "VALUES (%s, 'AA', 'Acity')",
                (uuid4(),),
            )
            connection.execute(
                "INSERT INTO platform_party.parties "
                "(id, tenant_id, party_number, party_type, display_name) "
                "VALUES (%s, %s, 'P1', 'person', 'Parent')",
                (party_id, tenant_a),
            )
            connection.execute(
                "INSERT INTO platform_geo.addresses "
                "(id, tenant_id, country_code, city, street_line1, formatted_address) "
                "VALUES (%s, %s, 'AA', 'Acity', 'X', 'X')",
                (address_id, tenant_b),
            )
            connection.execute(
                "INSERT INTO platform_party.party_address_assignments "
                "(id, tenant_id, party_id, address_id) VALUES (%s, %s, %s, %s)",
                (row_id, tenant_a, party_id, address_id),
            )
        connection.commit()

    with pytest.raises(Exception, match=new_revision):
        migrations.upgrade(postgres_database.migration_url, new_revision)

    table = {
        "geography": "platform_geo.cities",
        "geography_address": "platform_geo.addresses",
        "reference": "platform_ref.reference_values",
        "reference_external": "platform_ref.reference_values",
        "uom": "platform_uom.units_of_measure",
        "uom_base": "platform_uom.units_of_measure",
        "party": "platform_party.contact_points",
        "party_address": "platform_party.party_address_assignments",
    }[kind]
    with psycopg.connect(url) as connection:
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE id = %s", (row_id,)
        ).fetchone() == (1,)
        if kind == "geography":
            connection.execute(
                "UPDATE platform_geo.cities SET country_code = 'BB' WHERE id = %s", (row_id,)
            )
        elif kind == "geography_address":
            connection.execute(
                "UPDATE platform_geo.addresses SET subdivision_code = NULL WHERE id = %s",
                (row_id,),
            )
        elif kind == "reference":
            connection.execute(
                "INSERT INTO platform_ref.reference_sets "
                "(id, tenant_id, code, name, owning_module) "
                "VALUES (%s, %s, 'missing', 'Missing', 'test')",
                (uuid4(), tenant_a),
            )
        elif kind == "reference_external":
            connection.execute(
                "UPDATE platform_ref.reference_values SET external_id = NULL WHERE id = %s",
                (row_id,),
            )
        elif kind == "uom":
            connection.execute(
                "INSERT INTO platform_uom.measurement_categories "
                "(id, tenant_id, code, name, base_unit_code) "
                "VALUES (%s, %s, 'length', 'Length', 'm')",
                (uuid4(), tenant_a),
            )
        elif kind == "uom_base":
            connection.execute(
                "UPDATE platform_uom.units_of_measure SET is_base_unit = false WHERE id = %s",
                (row_id,),
            )
        elif kind == "party":
            connection.execute(
                "UPDATE platform_party.contact_points SET tenant_id = %s WHERE id = %s",
                (tenant_b, row_id),
            )
        else:
            connection.execute(
                "UPDATE platform_geo.addresses SET tenant_id = %s "
                "WHERE id = (SELECT address_id FROM platform_party.party_address_assignments "
                "WHERE id = %s)",
                (tenant_a, row_id),
            )
        connection.commit()
    migrations.upgrade(postgres_database.migration_url, new_revision)
