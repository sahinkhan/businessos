"""PostgreSQL regressions for Party allocation and Geography ambiguity."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_geography import (
    AddressRecord,
    AddressValidationResult,
    CreateAddress,
    ValidateAddress,
)
from businessos_party import CreateOrganizationParty, CreatePersonParty, PartyRecord
from sqlalchemy.exc import IntegrityError

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class _AllowAll:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _app(database: PostgreSQLTestDatabase) -> Any:
    modules = tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )
    app = create_application(
        Settings(environment="test", database_url=database.runtime_url),
        modules=modules,
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(database.migration_url)
    return app


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"hardening-{uuid4()}",
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


def _migration_url(database: PostgreSQLTestDatabase) -> str:
    return database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
@pytest.mark.postgres
async def test_party_number_retry_scope_exhaustion_and_other_integrity(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    import businessos_party.module as party_module

    app = _app(postgres_database)
    tenant_a, tenant_b = uuid4(), uuid4()
    context_a, context_b = _context(tenant_a), _context(tenant_b)
    await app.startup()
    try:
        person = await _command(
            app, CreatePersonParty(tenant_id=tenant_a, first_name="Ada", last_name="One"), context_a
        )
        organization = await _command(
            app, CreateOrganizationParty(tenant_id=tenant_a, legal_name="Acme"), context_a
        )
        assert isinstance(person, PartyRecord) and isinstance(organization, PartyRecord)
        assert person.party_number.startswith("PRT-") and len(person.party_number) == 20
        assert organization.party_number.startswith("PRT-") and len(organization.party_number) == 20
        assert person.id != organization.id

        candidates = iter([person.party_number, person.party_number, "PRT-1111111111111111"])
        with monkeypatch.context() as patch:
            patch.setattr(party_module, "_new_party_number", lambda: next(candidates))
            retried = await _command(
                app,
                CreatePersonParty(tenant_id=tenant_a, first_name="Ada", last_name="Two"),
                context_a,
            )
        assert isinstance(retried, PartyRecord)
        assert retried.party_number == "PRT-1111111111111111"
        assert retried.id != person.id

        # The uniqueness boundary is tenant-scoped, so the same number is legal elsewhere.
        with monkeypatch.context() as patch:
            patch.setattr(party_module, "_new_party_number", lambda: person.party_number)
            other_tenant = await _command(
                app, CreateOrganizationParty(tenant_id=tenant_b, legal_name="Elsewhere"), context_b
            )
        assert isinstance(other_tenant, PartyRecord)
        assert other_tenant.party_number == person.party_number

        with monkeypatch.context() as patch:
            patch.setattr(party_module, "_new_party_number", lambda: person.party_number)
            with pytest.raises(BusinessOSError) as exhausted:
                await _command(
                    app,
                    CreateOrganizationParty(tenant_id=tenant_a, legal_name="Cannot Allocate"),
                    context_a,
                )
        assert exhausted.value.code == "party_number_allocation_exhausted"
        assert exhausted.value.status_code == 409

        with monkeypatch.context() as patch:
            patch.setattr(party_module, "uuid4", lambda: person.id)
            patch.setattr(party_module, "_new_party_number", lambda: "PRT-2222222222222222")
            with pytest.raises(IntegrityError):
                await _command(
                    app,
                    CreatePersonParty(tenant_id=tenant_a, first_name="Wrong", last_name="Identity"),
                    context_a,
                )
        with psycopg.connect(_migration_url(postgres_database)) as connection:
            rows = connection.execute(
                "SELECT id, party_number FROM platform_party.parties WHERE tenant_id = %s",
                (tenant_a,),
            ).fetchall()
        assert len(rows) == 3
        assert len({number for _, number in rows}) == 3
        assert (person.id, person.party_number) in rows
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
async def test_concurrent_party_creates_retry_without_duplicate_number(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    import businessos_party.module as party_module

    app = _app(postgres_database)
    tenant_id = uuid4()
    context = _context(tenant_id)
    candidates = iter(["PRT-AAAAAAAAAAAAAAAA", "PRT-AAAAAAAAAAAAAAAA", "PRT-BBBBBBBBBBBBBBBB"])
    await app.startup()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(party_module, "_new_party_number", lambda: next(candidates))
            first, second = await asyncio.gather(
                _command(
                    app,
                    CreatePersonParty(tenant_id=tenant_id, first_name="First", last_name="Person"),
                    context,
                ),
                _command(
                    app,
                    CreateOrganizationParty(tenant_id=tenant_id, legal_name="Second Org"),
                    context,
                ),
            )
        assert isinstance(first, PartyRecord) and isinstance(second, PartyRecord)
        assert first.id != second.id
        assert {first.party_number, second.party_number} == {
            "PRT-AAAAAAAAAAAAAAAA",
            "PRT-BBBBBBBBBBBBBBBB",
        }
        with psycopg.connect(_migration_url(postgres_database)) as connection:
            rows = connection.execute(
                "SELECT party_number FROM platform_party.parties WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        assert len(rows) == 2 and len(set(rows)) == 2
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
async def test_geography_duplicate_locality_requires_hierarchy(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _app(postgres_database)
    tenant_id = uuid4()
    context = _context(tenant_id)
    sub_a, sub_b, sub_c = uuid4(), uuid4(), uuid4()
    with psycopg.connect(_migration_url(postgres_database)) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries (id, code, alpha3_code, numeric_code, name) "
            "VALUES (%s, 'AA', 'AAA', '001', 'A'), (%s, 'BB', 'BBB', '002', 'B')",
            (uuid4(), uuid4()),
        )
        connection.execute(
            "INSERT INTO platform_geo.subdivisions (id, country_code, code, name, category) "
            "VALUES (%s, 'AA', 'AA-1', 'A1', 'state'), "
            "(%s, 'AA', 'AA-2', 'A2', 'state'), (%s, 'BB', 'BB-1', 'B1', 'state')",
            (sub_a, sub_b, sub_c),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities "
            "(id, country_code, subdivision_id, name, postal_code_pattern) VALUES "
            "(%s, 'AA', %s, 'Springfield', '^[0-9]{4}$'), "
            "(%s, 'AA', %s, 'Springfield', '^[0-9]{5}$'), "
            "(%s, 'BB', %s, 'Springfield', NULL)",
            (uuid4(), sub_b, uuid4(), sub_a, uuid4(), sub_c),
        )
    await app.startup()
    try:
        unique = await _query(
            app,
            ValidateAddress(
                country_code="aa", subdivision_code="aa-1", city="Springfield", postal_code="12345"
            ),
            context,
        )
        assert isinstance(unique, AddressValidationResult) and unique.valid
        assert unique.normalized_subdivision_code == "AA-1"
        other_sub = await _query(
            app,
            ValidateAddress(
                country_code="AA", subdivision_code="AA-2", city="Springfield", postal_code="1234"
            ),
            context,
        )
        assert isinstance(other_sub, AddressValidationResult) and other_sub.valid

        ambiguous = await _query(
            app,
            ValidateAddress(country_code="AA", city="Springfield", postal_code="12345"),
            context,
        )
        assert isinstance(ambiguous, AddressValidationResult) and not ambiguous.valid
        assert [error.code for error in ambiguous.errors] == ["ambiguous_city"]
        with pytest.raises(BusinessOSError) as rejected:
            await _command(
                app,
                CreateAddress(
                    tenant_id=tenant_id,
                    country_code="AA",
                    city="Springfield",
                    street_line1="1 Main Street",
                    postal_code="12345",
                ),
                context,
            )
        assert rejected.value.code == "ambiguous_city"
        missing = await _query(app, ValidateAddress(country_code="AA", city="Unknown"), context)
        assert isinstance(missing, AddressValidationResult) and not missing.valid
        assert [error.code for error in missing.errors] == ["invalid_city"]
        other_country = await _query(
            app, ValidateAddress(country_code="BB", city="Springfield"), context
        )
        assert isinstance(other_country, AddressValidationResult) and other_country.valid

        address = await _command(
            app,
            CreateAddress(
                tenant_id=tenant_id,
                country_code=" aa ",
                subdivision_code=" aa-1 ",
                city=" Springfield ",
                street_line1="2 Main Street",
                postal_code=" 12345 ",
            ),
            context,
        )
        assert isinstance(address, AddressRecord)
        assert address.country_code == "AA" and address.subdivision_code == "AA-1"
        assert address.city == "Springfield" and address.postal_code == "12345"
        with psycopg.connect(_migration_url(postgres_database)) as connection:
            rows = connection.execute(
                "SELECT country_code, subdivision_code, city, postal_code "
                "FROM platform_geo.addresses "
                "WHERE id = %s",
                (address.id,),
            ).fetchall()
        assert rows == [("AA", "AA-1", "Springfield", "12345")]
    finally:
        await app.shutdown()
