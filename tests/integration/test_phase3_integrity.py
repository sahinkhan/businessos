"""PostgreSQL checks for the Phase 3 forward integrity revisions."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from decimal import Decimal
from threading import Event
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_geography import AddressRecord
from businessos_party import PartyRecord

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError, NotFoundError
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


class _DenySensitive:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return permission != "foundation.party.sensitive.read"


class _DenyCurrency:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return permission != "foundation.currency.read"


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


async def _query(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.query(message, context, dependencies)


@pytest.mark.integration
@pytest.mark.postgres
async def test_currency_public_dispatch_and_permissions(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    from businessos_currency import CurrencyRecord, GetCurrency, ListCurrencies, ResolveCurrency

    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    first, second = _context(uuid4()), _context(uuid4())
    try:
        usd = await _query(app, GetCurrency(code="USD"), first)
        assert isinstance(usd, CurrencyRecord)
        assert usd.code == "USD" and usd.minor_unit == 2
        assert await _query(app, GetCurrency(code="ZZZ"), first) is None
        assert await _query(app, ResolveCurrency(code="USD"), second) == usd
        page1 = await _query(app, ListCurrencies(limit=2), first)
        page2 = await _query(app, ListCurrencies(limit=2, offset=2), second)
        assert isinstance(page1, list) and isinstance(page2, list)
        assert [item.code for item in page1] == ["AED", "AUD"]
        assert [item.code for item in page2] == ["BDT", "BRL"]
        assert await _query(app, ListCurrencies(), first) == await _query(
            app, ListCurrencies(), second
        )
        migration_url = postgres_database.migration_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                "UPDATE platform_currency.currencies SET is_active = false WHERE code = 'USD'"
            )
        assert await _query(app, GetCurrency(code="USD"), first) is not None
        active = await _query(app, ListCurrencies(), first)
        all_codes = await _query(app, ListCurrencies(active_only=False), first)
        assert "USD" not in [item.code for item in cast(list[CurrencyRecord], active)]
        assert "USD" in [item.code for item in cast(list[CurrencyRecord], all_codes)]
    finally:
        await app.shutdown()

    denied = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_DenyCurrency()),
    )
    await denied.startup()
    try:
        with pytest.raises(BusinessOSError):
            await _query(denied, GetCurrency(code="USD"), first)
    finally:
        await denied.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_uom_base_move_and_rounding_database_integrity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    tenant_id, base_id, other_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(url) as connection:
        for code in ("length", "distance"):
            connection.execute(
                "INSERT INTO platform_uom.measurement_categories "
                "(id, tenant_id, code, name, base_unit_code) VALUES (%s, %s, %s, %s, 'm')",
                (uuid4(), tenant_id, code, code),
            )
        connection.execute(
            "INSERT INTO platform_uom.units_of_measure "
            "(id, tenant_id, category_code, code, name, symbol, is_base_unit) "
            "VALUES (%s, %s, 'length', 'm', 'Meter', 'm', true)",
            (base_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_uom.units_of_measure "
            "(id, tenant_id, category_code, code, name, symbol, conversion_ratio) "
            "VALUES (%s, %s, 'length', 'cm', 'Centimeter', 'cm', 0.01)",
            (other_id, tenant_id),
        )
        connection.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE platform_uom.units_of_measure SET category_code = 'distance' WHERE id = %s",
                (base_id,),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE platform_uom.units_of_measure SET is_base_unit = true WHERE id = %s",
                (other_id,),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE platform_uom.measurement_categories SET base_unit_code = 'cm' "
                "WHERE tenant_id = %s AND code = 'length'",
                (tenant_id,),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE platform_uom.units_of_measure SET rounding_mode = 'BAD' WHERE id = %s",
                (other_id,),
            )
        connection.rollback()
        connection.execute("DELETE FROM platform_uom.units_of_measure WHERE id = %s", (other_id,))
        connection.execute(
            "UPDATE platform_uom.units_of_measure SET category_code = 'distance' WHERE id = %s",
            (base_id,),
        )
        assert connection.execute(
            "SELECT category_code FROM platform_uom.units_of_measure WHERE id = %s", (base_id,)
        ).fetchone() == ("distance",)


@pytest.mark.integration
@pytest.mark.postgres
def test_uom_invalid_rounding_preflight_preserves_rows(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    migrations = app.runtime.migrations
    migrations.upgrade(postgres_database.migration_url, "uom_0001")
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    tenant_id, unit_id = uuid4(), uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO platform_uom.measurement_categories "
            "(id, tenant_id, code, name, base_unit_code) VALUES (%s, %s, 'length', 'Length', 'm')",
            (uuid4(), tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_uom.units_of_measure "
            "(id, tenant_id, category_code, code, name, symbol, is_base_unit, rounding_mode) "
            "VALUES (%s, %s, 'length', 'm', 'Meter', 'm', true, 'BAD')",
            (unit_id, tenant_id),
        )
    with pytest.raises(Exception, match="unsupported rounding mode"):
        migrations.upgrade(postgres_database.migration_url, "uom_0002")
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT rounding_mode FROM platform_uom.units_of_measure WHERE id = %s", (unit_id,)
        ).fetchone() == ("BAD",)
        connection.execute(
            "UPDATE platform_uom.units_of_measure SET rounding_mode = 'ROUND_HALF_UP' "
            "WHERE id = %s",
            (unit_id,),
        )
    migrations.upgrade(postgres_database.migration_url, "uom_0002")


@pytest.mark.integration
@pytest.mark.postgres
async def test_phase3_commands_enforce_parent_and_tenant_integrity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    from businessos_geography import (
        AddressValidationResult,
        CreateAddress,
        GetAddress,
        RegisterCountry,
        ValidateAddress,
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
    sub_a, sub_b = uuid4(), uuid4()
    migration_url = postgres_database.migration_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(migration_url) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries "
            "(id, code, alpha3_code, numeric_code, name, currency_code, address_format) "
            "VALUES (%s, 'AA', 'AAA', '001', 'A', 'USD', "
            '\'{"required_fields":["postal_code"]}\'::jsonb), '
            "(%s, 'BB', 'BBB', '002', 'B', 'EUR', '{}'::jsonb)",
            (uuid4(), uuid4()),
        )
        connection.execute(
            "INSERT INTO platform_geo.subdivisions (id, country_code, code, name, category) "
            "VALUES (%s, 'AA', 'AA-1', 'A1', 'state'), "
            "(%s, 'BB', 'BB-1', 'B1', 'state')",
            (sub_a, sub_b),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities "
            "(id, country_code, subdivision_id, name, postal_code_pattern) "
            "VALUES (%s, 'AA', %s, 'Acity', '^[0-9]{4}$')",
            (uuid4(), sub_a),
        )
    await app.startup()
    try:
        with pytest.raises(NotFoundError, match="No command handler for RegisterCountry"):
            await _command(
                app,
                RegisterCountry(code="CC", alpha3_code="CCC", numeric_code="003", name="C"),
                a,
            )
        invalid = await _query(
            app,
            ValidateAddress(
                country_code="aa",
                subdivision_code="aa-1",
                city="Acity",
                postal_code="bad",
                street_line1="1 A",
            ),
            a,
        )
        assert isinstance(invalid, AddressValidationResult)
        assert not invalid.valid
        assert invalid.normalized_country_code == "AA"
        assert [error.code for error in invalid.errors] == ["invalid_postal_code"]
        address_a = await _command(
            app,
            CreateAddress(
                tenant_id=tenant_a,
                country_code=" aa ",
                subdivision_code=" aa-1 ",
                city=" Acity ",
                postal_code=" 1234 ",
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
                postal_code="1234",
                street_line1="1 B",
            ),
            b,
        )
        assert isinstance(address_a, AddressRecord)
        assert isinstance(address_b, AddressRecord)
        assert (
            address_a.country_code,
            address_a.subdivision_code,
            address_a.city,
            address_a.postal_code,
        ) == ("AA", "AA-1", "Acity", "1234")
        assert await _query(app, GetAddress(address_id=address_a.id), a) == address_a
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
def test_runtime_role_cannot_mutate_global_geography_or_currency(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    runtime_url = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO platform_geo.countries "
                "(id, code, alpha3_code, numeric_code, name) "
                "VALUES (%s, 'AA', 'AAA', '001', 'A')",
                (uuid4(),),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE platform_currency.currencies SET name = 'changed' WHERE code = 'USD'"
            )
        connection.rollback()
        assert connection.execute(
            "SELECT name, minor_unit, source_version FROM platform_currency.currencies "
            "WHERE code = 'USD'"
        ).fetchone() == ("US Dollar", 2, 1)


@pytest.mark.integration
@pytest.mark.postgres
def test_trusted_geography_change_sees_all_tenant_dependents(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    migration_url = postgres_database.migration_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    city_id = uuid4()
    tenants = (uuid4(), uuid4())
    with psycopg.connect(migration_url) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries "
            "(id, code, alpha3_code, numeric_code, name, currency_code) "
            "VALUES (%s, 'AA', 'AAA', '001', 'A', 'USD')",
            (uuid4(),),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities (id, country_code, name) "
            "VALUES (%s, 'AA', 'Shared City')",
            (city_id,),
        )
        for tenant_id in tenants:
            connection.execute(
                "INSERT INTO platform_geo.addresses "
                "(id, tenant_id, country_code, city, street_line1, formatted_address) "
                "VALUES (%s, %s, 'AA', 'Shared City', 'Street', 'Street')",
                (uuid4(), tenant_id),
            )
        connection.commit()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "UPDATE platform_geo.cities SET name = 'Renamed' WHERE id = %s", (city_id,)
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute("DELETE FROM platform_geo.cities WHERE id = %s", (city_id,))
        connection.rollback()
        connection.execute(
            "UPDATE platform_geo.cities SET is_active = false WHERE id = %s", (city_id,)
        )
        assert connection.execute(
            "SELECT count(DISTINCT tenant_id) FROM platform_geo.addresses "
            "WHERE country_code = 'AA' AND city = 'Shared City'"
        ).fetchone() == (2,)
        connection.commit()


@pytest.mark.integration
@pytest.mark.postgres
def test_trusted_city_change_waits_for_concurrent_address_write(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    migration_url = postgres_database.migration_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    runtime_url = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://", 1)
    city_id = uuid4()
    tenant_id = uuid4()
    with psycopg.connect(migration_url) as trusted:
        trusted.execute(
            "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
            "VALUES (%s, 'AA', 'AAA', '001', 'A')",
            (uuid4(),),
        )
        trusted.execute(
            "INSERT INTO platform_geo.cities (id, country_code, name) "
            "VALUES (%s, 'AA', 'Shared City')",
            (city_id,),
        )
        trusted.commit()

    started = Event()

    def rename_city() -> None:
        with psycopg.connect(migration_url) as trusted:
            started.set()
            trusted.execute(
                "UPDATE platform_geo.cities SET name = 'Renamed' WHERE id = %s", (city_id,)
            )

    with psycopg.connect(runtime_url) as tenant, ThreadPoolExecutor(max_workers=1) as workers:
        tenant.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        tenant.execute(
            "INSERT INTO platform_geo.addresses "
            "(id, tenant_id, country_code, city, street_line1, formatted_address) "
            "VALUES (%s, %s, 'AA', 'Shared City', 'Street', 'Street')",
            (uuid4(), tenant_id),
        )
        future = workers.submit(rename_city)
        assert started.wait(5)
        with pytest.raises(FutureTimeoutError):
            future.result(timeout=0.2)
        tenant.commit()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            future.result(timeout=5)

    with psycopg.connect(migration_url) as trusted:
        assert trusted.execute(
            "SELECT name FROM platform_geo.cities WHERE id = %s", (city_id,)
        ).fetchone() == ("Shared City",)


@pytest.mark.integration
@pytest.mark.postgres
async def test_party_sensitive_projection_matching_and_bounded_search(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    from businessos_party import (
        AddContactPoint,
        AddExternalIdentifier,
        CreateOrganizationParty,
        CreatePersonParty,
        FullPartyRecord,
        GetFullParty,
        GetSensitiveFullParty,
        MatchPartyDuplicates,
        SearchParties,
    )
    from businessos_party.contracts import DuplicateMatchResult

    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    context = _context(tenant_id)
    other_tenant = uuid4()
    await app.startup()
    try:
        first = await _command(
            app,
            CreateOrganizationParty(
                tenant_id=tenant_id,
                legal_name="Acme Limited",
                tax_identifier="TAX-SECRET",
                registration_number="REG-SECRET",
            ),
            context,
        )
        second = await _command(
            app,
            CreateOrganizationParty(
                tenant_id=tenant_id,
                legal_name="Acme Duplicate",
                tax_identifier="TAX-SECRET",
            ),
            context,
        )
        assert isinstance(first, PartyRecord)
        assert isinstance(second, PartyRecord)
        person = await _command(
            app,
            CreatePersonParty(tenant_id=tenant_id, first_name="Acme", last_name="Limited"),
            context,
        )
        assert isinstance(person, PartyRecord)
        unrelated = await _command(
            app, CreateOrganizationParty(tenant_id=tenant_id, legal_name="Unrelated"), context
        )
        assert isinstance(unrelated, PartyRecord)
        other = await _command(
            app,
            CreateOrganizationParty(
                tenant_id=other_tenant,
                legal_name="Acme Other Tenant",
                tax_identifier="TAX-SECRET",
            ),
            _context(other_tenant),
        )
        assert isinstance(other, PartyRecord)
        await _command(
            app,
            AddContactPoint(
                tenant_id=tenant_id,
                party_id=first.id,
                channel_type="email",
                value="secret@example.test",
                is_verified=True,
            ),
            context,
        )
        await _command(
            app,
            AddExternalIdentifier(
                tenant_id=tenant_id,
                party_id=first.id,
                provider="restricted",
                identifier_value="SECRET-ID",
                is_sensitive=True,
            ),
            context,
        )
        await _command(
            app,
            AddExternalIdentifier(
                tenant_id=tenant_id,
                party_id=second.id,
                provider="RESTRICTED",
                identifier_value="SECRET-ID",
                is_sensitive=True,
            ),
            context,
        )
        await _command(
            app,
            AddContactPoint(
                tenant_id=tenant_id,
                party_id=person.id,
                channel_type="email",
                value="secret@example.test",
                is_verified=True,
            ),
            context,
        )
        public = await _query(app, GetFullParty(tenant_id=tenant_id, party_id=first.id), context)
        assert isinstance(public, FullPartyRecord)
        assert public.organization_profile is not None
        assert public.organization_profile.tax_identifier is None
        assert public.organization_profile.registration_number is None
        assert public.contacts == []
        assert public.identifiers == []

        sensitive = await _query(
            app, GetSensitiveFullParty(tenant_id=tenant_id, party_id=first.id), context
        )
        assert isinstance(sensitive, FullPartyRecord)
        assert sensitive.organization_profile is not None
        assert sensitive.organization_profile.tax_identifier == "TAX-SECRET"
        assert sensitive.contacts[0].value == "secret@example.test"
        assert sensitive.identifiers[0].identifier_value == "SECRET-ID"

        matches = await _query(
            app, MatchPartyDuplicates(tenant_id=tenant_id, party_id=first.id), context
        )
        assert isinstance(matches, DuplicateMatchResult)
        assert [(candidate.party_id, candidate.reasons) for candidate in matches.candidates] == [
            (second.id, ("external_identifier", "tax_identifier"))
        ]
        page = await _query(app, SearchParties(tenant_id=tenant_id, query="Acme", limit=1), context)
        assert isinstance(page, list)
        assert len(page) == 1
        next_page = await _query(
            app, SearchParties(tenant_id=tenant_id, query="Acme", limit=1, offset=1), context
        )
        assert isinstance(next_page, list)
        assert len(next_page) == 1
        assert page[0].id != next_page[0].id
        assert unrelated.id not in {candidate.party_id for candidate in matches.candidates}
        assert other.id not in {candidate.party_id for candidate in matches.candidates}
    finally:
        await app.shutdown()

    denied_app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_DenySensitive()),
    )
    await denied_app.startup()
    try:
        public = await _query(
            denied_app, GetFullParty(tenant_id=tenant_id, party_id=first.id), context
        )
        assert isinstance(public, FullPartyRecord)
        with pytest.raises(BusinessOSError) as denied:
            await _query(
                denied_app, GetSensitiveFullParty(tenant_id=tenant_id, party_id=first.id), context
            )
        assert denied.value.status_code == 403
    finally:
        await denied_app.shutdown()


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
        ("geography_currency", "geography_0002", "geography_0003"),
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
        elif kind == "geography_currency":
            connection.execute(
                "INSERT INTO platform_geo.countries "
                "(id, code, alpha3_code, numeric_code, name, currency_code) "
                "VALUES (%s, 'AA', 'AAA', '001', 'A', 'ZZZ')",
                (row_id,),
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
        "geography_currency": "platform_geo.countries",
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
        elif kind == "geography_currency":
            connection.execute(
                "UPDATE platform_geo.countries SET currency_code = 'USD' WHERE id = %s",
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
