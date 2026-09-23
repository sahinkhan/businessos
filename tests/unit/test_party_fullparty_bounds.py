"""The aggregate contract has SQL bounds and complete-or-overflow behavior."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from businessos_party import (
    FullPartyRecord,
    FullPartyRecordV2,
    GetFullParty,
    GetFullPartyV2,
    GetSensitiveFullParty,
    GetSensitiveFullPartyV2,
    PartyModule,
    PartyRecord,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.messages import HandlingContext


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def first(self) -> SimpleNamespace | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[SimpleNamespace]:
        return self.rows


class _Persistence:
    def __init__(self, tenant_id: UUID, party_id: UUID, counts: dict[str, int]) -> None:
        self.tenant_id = tenant_id
        self.party_id = party_id
        self.counts = counts
        self.sql: list[str] = []

    async def execute(self, statement: Select[Any]) -> _Result:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
                compile_kwargs={"literal_binds": True},
            )
        )
        self.sql.append(sql)
        if "person_profiles" in sql:
            return _Result([])
        for collection, table in (
            ("contacts", "contact_points"),
            ("addresses", "party_address_assignments"),
            ("identifiers", "external_identifiers"),
        ):
            if f"platform_party.{table}" not in sql:
                continue
            assert "LIMIT 101" in sql
            assert f"ORDER BY platform_party.{table}.id" in sql
            now = datetime.now(UTC)
            rows: list[SimpleNamespace] = []
            for number in range(min(self.counts[collection], 101)):
                values: dict[str, object] = {
                    "id": UUID(int=number + 1),
                    "tenant_id": self.tenant_id,
                    "party_id": self.party_id,
                    "created_at": now,
                }
                if collection == "contacts":
                    values.update(
                        channel_type="email",
                        value=f"{number}@example.test",
                        purpose="primary",
                        is_primary=False,
                        is_verified=False,
                    )
                elif collection == "addresses":
                    values.update(
                        address_id=uuid4(), purpose="billing", is_primary=False, is_active=True
                    )
                else:
                    values.update(
                        provider="test", identifier_value=f"ID-{number}", is_sensitive=False
                    )
                rows.append(SimpleNamespace(**values))
            return _Result(rows)
        raise AssertionError(f"unexpected aggregate SQL: {sql}")


def _fixture(
    counts: dict[str, int],
) -> tuple[PartyModule, HandlingContext, _Persistence, UUID, UUID]:
    tenant_id, party_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    party = PartyRecord(
        id=party_id,
        tenant_id=tenant_id,
        party_number="P-1",
        party_type="person",
        display_name="Bounded Party",
        created_at=now,
        updated_at=now,
    )
    module = PartyModule()

    async def get_party(_query: object, _context: object) -> PartyRecord:
        return party

    module._get_party = cast(Any, get_party)  # type: ignore[method-assign]
    persistence = _Persistence(tenant_id, party_id, counts)
    request = RequestContext(
        correlation_id="fullparty-unit",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        ),
    )
    context = cast(
        HandlingContext,
        SimpleNamespace(request=request, unit_of_work=SimpleNamespace(persistence=persistence)),
    )
    return module, context, persistence, tenant_id, party_id


QUERY_CASES = (
    (GetFullParty, "_get_full_party", FullPartyRecord, False),
    (GetSensitiveFullParty, "_get_sensitive_full_party", FullPartyRecord, True),
    (GetFullPartyV2, "_get_full_party_v2", FullPartyRecordV2, False),
    (GetSensitiveFullPartyV2, "_get_sensitive_full_party_v2", FullPartyRecordV2, True),
)


@pytest.mark.parametrize("query_type,handler_name,record_type,sensitive", QUERY_CASES)
@pytest.mark.parametrize("collection", ("contacts", "addresses", "identifiers"))
@pytest.mark.parametrize("count", (0, 1, 99, 100, 101))
async def test_full_party_is_complete_or_overflow(
    query_type: type[Any],
    handler_name: str,
    record_type: type[FullPartyRecord],
    sensitive: bool,
    collection: str,
    count: int,
) -> None:
    counts = {"contacts": 0, "addresses": 0, "identifiers": 0}
    counts[collection] = count
    module, context, persistence, tenant_id, party_id = _fixture(counts)
    handler = getattr(module, handler_name)
    query = query_type(tenant_id=tenant_id, party_id=party_id)

    if count == 101 and (collection != "contacts" or sensitive):
        with pytest.raises(BusinessOSError) as raised:
            await handler(query, context)
        assert raised.value.code == "full_party_aggregate_too_large"
        assert raised.value.status_code == 409
        assert raised.value.details is None
        assert "contact" not in raised.value.message.lower()
        assert "identifier" not in raised.value.message.lower()
    else:
        record = await handler(query, context)
        assert type(record) is record_type
        assert len(getattr(record, collection)) == (
            0 if collection == "contacts" and not sensitive else count
        )
        assert len(record.contacts) + len(record.addresses) + len(record.identifiers) == (
            0 if collection == "contacts" and not sensitive else count
        )

    child_sql = [sql for sql in persistence.sql if "LIMIT 101" in sql]
    expected_queries = 3 if sensitive else 2
    if count == 101 and collection == "contacts" and sensitive:
        expected_queries = 1
    elif count == 101 and collection == "addresses":
        expected_queries = 2 if sensitive else 1
    assert len(child_sql) == expected_queries
    if not sensitive:
        assert not any("contact_points" in sql for sql in persistence.sql)
        if any("external_identifiers" in sql for sql in persistence.sql):
            assert any(
                "is_sensitive is false" in sql.lower()
                for sql in persistence.sql
                if "external_identifiers" in sql
            )


@pytest.mark.parametrize("query_type,handler_name,_,_sensitive", QUERY_CASES)
async def test_overflow_in_later_collection_fails_whole_aggregate(
    query_type: type[Any], handler_name: str, _: object, _sensitive: bool
) -> None:
    counts = {"contacts": 1, "addresses": 1, "identifiers": 101}
    module, context, _, tenant_id, party_id = _fixture(counts)
    with pytest.raises(BusinessOSError, match="supported bound") as raised:
        await getattr(module, handler_name)(
            query_type(tenant_id=tenant_id, party_id=party_id), context
        )
    assert raised.value.code == "full_party_aggregate_too_large"
