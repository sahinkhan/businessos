"""ADR-013 dispatch, PostgreSQL bounds, tenant isolation, and child migration paths."""

# pyright: reportPrivateUsage=false

from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_party import (
    AddContactPoint,
    AddExternalIdentifier,
    AddPartyRelationship,
    AssignPartyAddress,
    ContactPointRecord,
    CreateOrganizationParty,
    CreatePersonParty,
    ExternalIdentifierRecord,
    FullPartyRecord,
    FullPartyRecordV2,
    GetFullParty,
    GetFullPartyV2,
    GetSensitiveFullParty,
    GetSensitiveFullPartyV2,
    ListPartyAddresses,
    ListPartyContacts,
    ListPartyIdentifiers,
    ListPartyRelationships,
    ListSensitivePartyIdentifiers,
    PartyAddressAssignmentRecord,
    PartyRecord,
    PartyRelationshipRecord,
)

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.errors import BusinessOSError
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase3_integrity import (
    _AllowAll,
    _command,
    _context,
    _DenySensitive,
    _foundation_modules,
    _query,
)


def _migration_url(database: PostgreSQLTestDatabase) -> str:
    return database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_address(database: PostgreSQLTestDatabase, tenant_id: UUID) -> UUID:
    address_id = uuid4()
    with psycopg.connect(_migration_url(database)) as connection:
        connection.execute(
            "INSERT INTO platform_geo.countries "
            "(id, code, alpha3_code, numeric_code, name) "
            "VALUES (%s, 'XZ', 'XZZ', '999', 'Test Country')",
            (uuid4(),),
        )
        connection.execute(
            "INSERT INTO platform_geo.cities (id, country_code, name) "
            "VALUES (%s, 'XZ', 'Test City')",
            (uuid4(),),
        )
        connection.execute(
            "INSERT INTO platform_geo.addresses "
            "(id, tenant_id, country_code, city, street_line1, formatted_address) "
            "VALUES (%s, %s, 'XZ', 'Test City', '1 Test Street', '1 Test Street')",
            (address_id, tenant_id),
        )
    return address_id


def _insert_children(
    database: PostgreSQLTestDatabase,
    collection: str,
    tenant_id: UUID,
    party_id: UUID,
    *,
    start: int,
    count: int,
    address_id: UUID | None = None,
) -> None:
    values: list[tuple[Any, ...]] = []
    if collection == "contacts":
        statement = (
            "INSERT INTO platform_party.contact_points "
            "(id, tenant_id, party_id, channel_type, value) "
            "VALUES (%s, %s, %s, 'email', %s)"
        )
        values = [
            (uuid4(), tenant_id, party_id, f"bounded-{number}@example.test")
            for number in range(start, start + count)
        ]
    elif collection == "addresses":
        assert address_id is not None
        statement = (
            "INSERT INTO platform_party.party_address_assignments "
            "(id, tenant_id, party_id, address_id) VALUES (%s, %s, %s, %s)"
        )
        values = [(uuid4(), tenant_id, party_id, address_id) for _ in range(count)]
    else:
        statement = (
            "INSERT INTO platform_party.external_identifiers "
            "(id, tenant_id, party_id, provider, identifier_value) "
            "VALUES (%s, %s, %s, 'bounded', %s)"
        )
        values = [
            (uuid4(), tenant_id, party_id, f"ID-{party_id}-{number}")
            for number in range(start, start + count)
        ]
    with psycopg.connect(_migration_url(database)) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(statement, values)


@pytest.mark.integration
@pytest.mark.postgres
async def test_full_party_complete_at_99_and_100_then_overflows_at_101(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    context = _context(tenant_id)
    address_id = _seed_address(postgres_database, tenant_id)
    await app.startup()
    try:
        assert app.runtime.contracts.get("foundation.party.full-read.v2").version == "2.0"
        party_module = app.runtime.modules.get("foundation.party").module
        assert party_module.manifest.version == "0.4.0"
        advertised = {item.contract_id for item in party_module.manifest.api_contracts}
        assert {
            "foundation.party.query.get-full-party.v1",
            "foundation.party.query.get-sensitive-full-party.v1",
            "foundation.party.query.get-full-party.v2",
            "foundation.party.query.get-sensitive-full-party.v2",
        } <= advertised
        for collection in ("contacts", "addresses", "identifiers"):
            party = await _command(
                app,
                CreatePersonParty(tenant_id=tenant_id, first_name="Bounded", last_name=collection),
                context,
            )
            assert isinstance(party, PartyRecord)
            _insert_children(
                postgres_database,
                collection,
                tenant_id,
                party.id,
                start=0,
                count=99,
                address_id=address_id,
            )
            query_types = (
                (
                    (GetSensitiveFullParty, FullPartyRecord),
                    (GetSensitiveFullPartyV2, FullPartyRecordV2),
                )
                if collection == "contacts"
                else (
                    (GetFullParty, FullPartyRecord),
                    (GetSensitiveFullParty, FullPartyRecord),
                    (GetFullPartyV2, FullPartyRecordV2),
                    (GetSensitiveFullPartyV2, FullPartyRecordV2),
                )
            )
            for expected_count in (99, 100):
                if expected_count == 100:
                    _insert_children(
                        postgres_database,
                        collection,
                        tenant_id,
                        party.id,
                        start=99,
                        count=1,
                        address_id=address_id,
                    )
                for query_type, record_type in query_types:
                    record = await _query(
                        app, query_type(tenant_id=tenant_id, party_id=party.id), context
                    )
                    assert type(record) is record_type
                    assert len(getattr(record, collection)) == expected_count
            _insert_children(
                postgres_database,
                collection,
                tenant_id,
                party.id,
                start=100,
                count=1,
                address_id=address_id,
            )
            for query_type, _ in query_types:
                with pytest.raises(BusinessOSError) as raised:
                    await _query(app, query_type(tenant_id=tenant_id, party_id=party.id), context)
                assert raised.value.code == "full_party_aggregate_too_large"
                assert raised.value.status_code == 409
                assert raised.value.details is None
                assert "101" not in raised.value.message
                assert collection not in raised.value.message
            if collection == "contacts":
                for query_type in (GetFullParty, GetFullPartyV2):
                    general = await _query(
                        app, query_type(tenant_id=tenant_id, party_id=party.id), context
                    )
                    assert isinstance(general, FullPartyRecord)
                    assert general.contacts == []
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
async def test_child_pagination_redaction_permissions_and_tenant_scope(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id, other_tenant_id = uuid4(), uuid4()
    context, other_context = _context(tenant_id), _context(other_tenant_id)
    address_id = _seed_address(postgres_database, tenant_id)
    await app.startup()
    try:
        party = await _command(
            app,
            CreateOrganizationParty(
                tenant_id=tenant_id,
                legal_name="Private Company",
                tax_identifier="SECRET-TAX",
                registration_number="SECRET-REG",
            ),
            context,
        )
        other = await _command(
            app,
            CreatePersonParty(tenant_id=other_tenant_id, first_name="Other", last_name="Tenant"),
            other_context,
        )
        assert isinstance(party, PartyRecord) and isinstance(other, PartyRecord)
        person = await _command(
            app,
            CreatePersonParty(
                tenant_id=tenant_id,
                first_name="Private",
                last_name="Person",
                date_of_birth=date(1980, 1, 2),
            ),
            context,
        )
        assert isinstance(person, PartyRecord)
        for number in range(3):
            await _command(
                app,
                AddContactPoint(
                    tenant_id=tenant_id,
                    party_id=party.id,
                    channel_type="email",
                    value=f"private-{number}@example.test",
                ),
                context,
            )
            await _command(
                app,
                AssignPartyAddress(tenant_id=tenant_id, party_id=party.id, address_id=address_id),
                context,
            )
            await _command(
                app,
                AddExternalIdentifier(
                    tenant_id=tenant_id,
                    party_id=party.id,
                    provider="public",
                    identifier_value=f"PUB-{number}",
                ),
                context,
            )
        await _command(
            app,
            AddExternalIdentifier(
                tenant_id=tenant_id,
                party_id=party.id,
                provider="private",
                identifier_value="SECRET-ID",
                is_sensitive=True,
            ),
            context,
        )
        for number in range(3):
            related = await _command(
                app,
                CreatePersonParty(tenant_id=tenant_id, first_name="Related", last_name=str(number)),
                context,
            )
            assert isinstance(related, PartyRecord)
            await _command(
                app,
                AddPartyRelationship(
                    tenant_id=tenant_id,
                    from_party_id=party.id,
                    to_party_id=related.id,
                    relationship_type="related",
                ),
                context,
            )

        general = await _query(app, GetFullPartyV2(tenant_id=tenant_id, party_id=party.id), context)
        sensitive = await _query(
            app, GetSensitiveFullPartyV2(tenant_id=tenant_id, party_id=party.id), context
        )
        assert isinstance(general, FullPartyRecordV2)
        assert isinstance(sensitive, FullPartyRecordV2)
        assert general.contacts == [] and len(general.addresses) == 3
        assert general.organization_profile is not None
        assert general.organization_profile.tax_identifier is None
        assert general.organization_profile.registration_number is None
        assert len(general.identifiers) == 3
        assert sensitive.organization_profile is not None
        assert sensitive.organization_profile.tax_identifier == "SECRET-TAX"
        assert len(sensitive.contacts) == 3 and len(sensitive.identifiers) == 4
        public_person = await _query(
            app, GetFullPartyV2(tenant_id=tenant_id, party_id=person.id), context
        )
        sensitive_person = await _query(
            app, GetSensitiveFullPartyV2(tenant_id=tenant_id, party_id=person.id), context
        )
        assert isinstance(public_person, FullPartyRecordV2)
        assert isinstance(sensitive_person, FullPartyRecordV2)
        assert public_person.person_profile is not None
        assert sensitive_person.person_profile is not None
        assert public_person.person_profile.date_of_birth is None
        assert sensitive_person.person_profile.date_of_birth == date(1980, 1, 2)
        assert (
            await _query(app, GetFullPartyV2(tenant_id=tenant_id, party_id=other.id), context)
            is None
        )

        query_types = (
            ListPartyContacts,
            ListPartyAddresses,
            ListPartyIdentifiers,
            ListSensitivePartyIdentifiers,
            ListPartyRelationships,
        )
        for query_type in query_types:
            first = cast(
                list[
                    ContactPointRecord
                    | PartyAddressAssignmentRecord
                    | ExternalIdentifierRecord
                    | PartyRelationshipRecord
                ],
                await _query(
                    app, query_type(tenant_id=tenant_id, party_id=party.id, limit=2), context
                ),
            )
            second = cast(
                list[
                    ContactPointRecord
                    | PartyAddressAssignmentRecord
                    | ExternalIdentifierRecord
                    | PartyRelationshipRecord
                ],
                await _query(
                    app,
                    query_type(tenant_id=tenant_id, party_id=party.id, limit=2, offset=2),
                    context,
                ),
            )
            default_page = cast(
                list[
                    ContactPointRecord
                    | PartyAddressAssignmentRecord
                    | ExternalIdentifierRecord
                    | PartyRelationshipRecord
                ],
                await _query(app, query_type(tenant_id=tenant_id, party_id=party.id), context),
            )
            maximum_page = cast(
                list[
                    ContactPointRecord
                    | PartyAddressAssignmentRecord
                    | ExternalIdentifierRecord
                    | PartyRelationshipRecord
                ],
                await _query(
                    app, query_type(tenant_id=tenant_id, party_id=party.id, limit=100), context
                ),
            )
            assert isinstance(first, list) and isinstance(second, list)
            assert isinstance(default_page, list) and isinstance(maximum_page, list)
            assert len(first) == 2 and len(second) >= 1
            ids = [item.id for item in first + second]
            assert ids == sorted(ids) and len(ids) == len(set(ids))
            assert [item.id for item in default_page] == [item.id for item in maximum_page]
            with pytest.raises(BusinessOSError) as missing:
                await _query(app, query_type(tenant_id=tenant_id, party_id=other.id), context)
            assert missing.value.status_code == 404
        public_ids = cast(
            list[ExternalIdentifierRecord],
            await _query(
                app, ListPartyIdentifiers(tenant_id=tenant_id, party_id=party.id), context
            ),
        )
        sensitive_ids = cast(
            list[ExternalIdentifierRecord],
            await _query(
                app, ListSensitivePartyIdentifiers(tenant_id=tenant_id, party_id=party.id), context
            ),
        )
        assert isinstance(public_ids, list) and isinstance(sensitive_ids, list)
        assert all(not item.is_sensitive for item in public_ids)
        assert any(item.identifier_value == "SECRET-ID" for item in sensitive_ids)
        assert (
            await _query(
                app, ListPartyContacts(tenant_id=other_tenant_id, party_id=other.id), other_context
            )
            == []
        )
    finally:
        await app.shutdown()

    denied = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=_foundation_modules(),
        authorizer=Authorizer(_DenySensitive()),
    )
    await denied.startup()
    try:
        for denied_query_type in (
            GetSensitiveFullParty,
            GetSensitiveFullPartyV2,
            ListPartyContacts,
            ListSensitivePartyIdentifiers,
        ):
            with pytest.raises(BusinessOSError) as denied_error:
                await _query(
                    denied, denied_query_type(tenant_id=tenant_id, party_id=party.id), context
                )
            assert denied_error.value.status_code == 403
        public = await _query(
            denied, GetFullPartyV2(tenant_id=tenant_id, party_id=party.id), context
        )
        assert isinstance(public, FullPartyRecordV2)
        assert public.contacts == []
    finally:
        await denied.shutdown()
