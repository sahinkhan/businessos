"""Unit tests for Phase 3 foundational modules: UoM, Geography, Reference Data, and Party."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from businessos_geography import (
    AddressFormatProviderContract,
    RegisterCountry,
)
from businessos_party import (
    CreateOrganizationParty,
    CreatePersonParty,
)
from businessos_reference_data import (
    RegisterReferenceSet,
)
from businessos_uom import (
    CreateUnitOfMeasure,
    UnitOfMeasureRecord,
    UomConversionService,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("query_type", "arguments"),
    (
        ("ListCountries", {}),
        ("ListSubdivisions", {"country_code": "US"}),
        ("ListReferenceSets", {"tenant_id": uuid4()}),
        ("ListReferenceValues", {"tenant_id": uuid4(), "set_code": "colors"}),
        ("ListMeasurementCategories", {"tenant_id": uuid4()}),
        ("ListUnitsOfMeasure", {"tenant_id": uuid4()}),
        ("ListPartyRelationships", {"tenant_id": uuid4(), "party_id": uuid4()}),
    ),
)
def test_phase3_collection_query_bounds(query_type: str, arguments: dict[str, object]) -> None:
    import businessos_geography
    import businessos_party
    import businessos_reference_data
    import businessos_uom

    query_class = next(
        getattr(module, query_type)
        for module in (
            businessos_geography,
            businessos_reference_data,
            businessos_uom,
            businessos_party,
        )
        if hasattr(module, query_type)
    )
    assert query_class(**arguments).limit == 50
    assert query_class(**arguments, limit=100, offset=100).offset == 100
    for extra in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        with pytest.raises(ValidationError):
            query_class(**arguments, **extra)


def test_uom_conversion_service_exact_arithmetic_and_round_trip() -> None:
    service = UomConversionService()
    tenant_id = uuid4()
    now = datetime.now()

    m = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="length",
        code="m",
        name="Meter",
        symbol="m",
        is_base_unit=True,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=4,
        rounding_mode="ROUND_HALF_UP",
        created_at=now,
    )

    km = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="length",
        code="km",
        name="Kilometer",
        symbol="km",
        is_base_unit=False,
        conversion_ratio=Decimal("1000.0"),
        conversion_offset=Decimal("0.0"),
        precision=3,
        rounding_mode="ROUND_HALF_UP",
        created_at=now,
    )

    # 1500 meters to kilometers = 1.5 km
    result = service.convert(Decimal("1500"), m, km)
    assert result.converted_amount == Decimal("1.500")
    assert result.from_unit == "m"
    assert result.to_unit == "km"

    # Round trip: 1.5 km to meters = 1500 m
    round_trip = service.convert(result.converted_amount, km, m)
    assert round_trip.converted_amount == Decimal("1500.0000")
    with pytest.raises(ValueError, match="different tenants"):
        service.convert(Decimal("1"), m, km.model_copy(update={"tenant_id": uuid4()}))


def test_uom_rounding_modes() -> None:
    service = UomConversionService()
    tenant_id = uuid4()
    now = datetime.now()

    base = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="currency",
        code="base_cur",
        name="Base Currency",
        symbol="$",
        is_base_unit=True,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=2,
        rounding_mode="ROUND_HALF_UP",
        created_at=now,
    )

    # Unit with precision 0 and different rounding modes
    half_up_unit = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="currency",
        code="half_up",
        name="Half Up",
        symbol="$",
        is_base_unit=False,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=0,
        rounding_mode="ROUND_HALF_UP",
        created_at=now,
    )
    floor_unit = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="currency",
        code="floor",
        name="Floor",
        symbol="$",
        is_base_unit=False,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=0,
        rounding_mode="ROUND_FLOOR",
        created_at=now,
    )
    ceil_unit = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="currency",
        code="ceil",
        name="Ceil",
        symbol="$",
        is_base_unit=False,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=0,
        rounding_mode="ROUND_CEILING",
        created_at=now,
    )

    assert service.convert(Decimal("2.5"), base, half_up_unit).converted_amount == Decimal("3")
    assert service.convert(Decimal("2.5"), base, floor_unit).converted_amount == Decimal("2")
    assert service.convert(Decimal("2.1"), base, ceil_unit).converted_amount == Decimal("3")

    for mode, amount, expected in (
        ("ROUND_HALF_UP", "2.5", "3"),
        ("ROUND_HALF_EVEN", "2.5", "2"),
        ("ROUND_FLOOR", "-2.1", "-3"),
        ("ROUND_CEILING", "2.1", "3"),
        ("ROUND_UP", "-2.1", "-3"),
        ("ROUND_DOWN", "-2.9", "-2"),
    ):
        target = half_up_unit.model_copy(update={"rounding_mode": mode})
        assert service.convert(Decimal(amount), base, target).converted_amount == Decimal(expected)

    with pytest.raises(ValidationError):
        UnitOfMeasureRecord.model_validate(half_up_unit.model_dump() | {"rounding_mode": "BAD"})
    with pytest.raises(ValidationError):
        CreateUnitOfMeasure.model_validate(
            {
                "tenant_id": tenant_id,
                "category_code": "length",
                "code": "bad",
                "name": "Bad",
                "symbol": "b",
                "rounding_mode": "BAD",
            }
        )


def test_uom_rejects_cross_category_conversion() -> None:
    service = UomConversionService()
    tenant_id = uuid4()
    now = datetime.now()

    meter = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="length",
        code="m",
        name="Meter",
        symbol="m",
        is_base_unit=True,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=2,
        created_at=now,
    )
    kg = UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="mass",
        code="kg",
        name="Kilogram",
        symbol="kg",
        is_base_unit=True,
        conversion_ratio=Decimal("1.0"),
        conversion_offset=Decimal("0.0"),
        precision=2,
        created_at=now,
    )

    with pytest.raises(ValueError, match="Cannot convert between different categories"):
        service.convert(Decimal("10"), meter, kg)


def test_geography_address_formatting_contract() -> None:
    formatter = AddressFormatProviderContract()
    formatted = formatter.format(
        street_line1="100 Market St",
        street_line2="Suite 400",
        city="San Francisco",
        subdivision_code="CA",
        postal_code="94105",
        country_code="US",
    )
    assert "100 Market St" in formatted
    assert "Suite 400" in formatted
    assert "San Francisco" in formatted
    assert "CA" in formatted
    assert "94105" in formatted
    assert "US" in formatted


def test_geography_validation_rules() -> None:
    # Country code must be ISO 2-letter uppercase
    with pytest.raises(ValidationError):
        RegisterCountry(
            code="USA",  # Should be 2 chars
            alpha3_code="USA",
            numeric_code="840",
            name="United States",
        )
    with pytest.raises(ValidationError):
        RegisterCountry(
            code="us",  # Should be uppercase
            alpha3_code="USA",
            numeric_code="840",
            name="United States",
        )


def test_reference_data_validation_rules() -> None:
    tenant_id = uuid4()
    # Reference set code pattern
    with pytest.raises(ValidationError):
        RegisterReferenceSet(
            tenant_id=tenant_id,
            code="INVALID CODE WITH SPACES",
            name="Invalid",
            owning_module="test",
        )

    # Valid reference set command
    cmd = RegisterReferenceSet(
        tenant_id=tenant_id,
        code="payment_terms",
        name="Payment Terms",
        owning_module="foundation.party",
    )
    assert cmd.code == "payment_terms"


def test_party_validation_rules() -> None:
    tenant_id = uuid4()

    # Person party validation
    person_cmd = CreatePersonParty(
        tenant_id=tenant_id,
        first_name="Jane",
        last_name="Doe",
        preferred_locale="en_US",
        preferred_currency="USD",
    )
    assert person_cmd.first_name == "Jane"
    assert person_cmd.last_name == "Doe"

    # Currency code must be 3 chars
    with pytest.raises(ValidationError):
        CreatePersonParty(
            tenant_id=tenant_id,
            first_name="Jane",
            last_name="Doe",
            preferred_currency="US_DOLLAR",
        )

    # Organization party validation
    org_cmd = CreateOrganizationParty(
        tenant_id=tenant_id,
        legal_name="Acme Corp Global Ltd",
        trade_name="Acme",
        tax_identifier="12-3456789",
    )
    assert org_cmd.legal_name == "Acme Corp Global Ltd"
