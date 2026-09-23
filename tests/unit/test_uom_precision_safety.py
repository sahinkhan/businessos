"""UoM decimal-place precision must remain executable after creation."""

from datetime import UTC, datetime
from decimal import Decimal, getcontext
from uuid import UUID, uuid4

import pytest
from businessos_uom import CreateUnitOfMeasure, UnitOfMeasureRecord, UomConversionService
from pydantic import ValidationError

from businessos.sdk import BusinessOSError


def _unit(
    tenant_id: UUID,
    code: str,
    precision: int,
    *,
    ratio: str = "1",
    rounding_mode: str = "ROUND_HALF_UP",
) -> UnitOfMeasureRecord:
    return UnitOfMeasureRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        category_code="mass",
        code=code,
        name="Unit",
        symbol="u",
        conversion_ratio=Decimal(ratio),
        precision=precision,
        rounding_mode=rounding_mode,
        created_at=datetime.now(UTC),
    )


def test_exact_audit_precision_29_conversion() -> None:
    tenant_id = uuid4()
    command = CreateUnitOfMeasure(
        tenant_id=tenant_id,
        category_code="mass",
        code="fine",
        name="Fine",
        symbol="f",
        precision=29,
    )
    source = _unit(tenant_id, "base", 2)
    target = _unit(tenant_id, "fine", command.precision)

    result = UomConversionService().convert(Decimal("1"), source, target)

    assert result.converted_amount == Decimal("1." + "0" * 29)
    assert result.converted_amount.as_tuple().exponent == -29


@pytest.mark.parametrize("places", [0, 2, 28, 29, 100])
@pytest.mark.parametrize("value", ["0", "1", "-1"])
def test_all_supported_precision_boundaries_are_executable(places: int, value: str) -> None:
    tenant_id = uuid4()
    command = CreateUnitOfMeasure(
        tenant_id=tenant_id,
        category_code="mass",
        code="target",
        name="Target",
        symbol="t",
        precision=places,
    )
    before = getcontext().prec
    result = UomConversionService().convert(
        Decimal(value), _unit(tenant_id, "base", 2), _unit(tenant_id, "target", command.precision)
    )
    assert result.converted_amount == Decimal(value)
    assert result.converted_amount.as_tuple().exponent == -places
    assert getcontext().prec == before


def test_maximum_plus_one_rejected_by_both_public_models() -> None:
    tenant_id = uuid4()
    with pytest.raises(ValidationError):
        CreateUnitOfMeasure(
            tenant_id=tenant_id,
            category_code="mass",
            code="too_fine",
            name="Too Fine",
            symbol="x",
            precision=101,
        )
    with pytest.raises(ValidationError):
        _unit(tenant_id, "too_fine", 101)


def test_large_magnitude_and_high_fractional_scale() -> None:
    tenant_id = uuid4()
    source = _unit(tenant_id, "base", 2)
    target = _unit(tenant_id, "fine", 100)
    service = UomConversionService()
    large = Decimal("9" * 64)
    assert service.convert(large, source, target).converted_amount == Decimal(
        "9" * 64 + "." + "0" * 100
    )
    tiny = Decimal("1E-100")
    assert service.convert(tiny, source, target).converted_amount == tiny


def test_multiplication_division_and_round_trip_at_precision_29() -> None:
    tenant_id = uuid4()
    base = _unit(tenant_id, "base", 29)
    doubled = _unit(tenant_id, "double", 29, ratio="2")
    tripled = _unit(tenant_id, "triple", 29, ratio="3")
    service = UomConversionService()
    assert service.convert(Decimal("1.25"), doubled, base).converted_amount == Decimal("2.5")
    third = service.convert(Decimal("1"), base, tripled).converted_amount
    assert third == Decimal("0." + "3" * 29)
    assert service.convert(Decimal("1.5"), doubled, tripled).converted_amount == Decimal("1")


@pytest.mark.parametrize(
    ("mode", "positive", "negative"),
    [
        ("ROUND_HALF_UP", "3", "-3"),
        ("ROUND_HALF_EVEN", "2", "-2"),
        ("ROUND_FLOOR", "2", "-3"),
        ("ROUND_CEILING", "3", "-2"),
        ("ROUND_UP", "3", "-3"),
        ("ROUND_DOWN", "2", "-2"),
    ],
)
def test_all_closed_rounding_modes_at_high_scale(mode: str, positive: str, negative: str) -> None:
    tenant_id = uuid4()
    source = _unit(tenant_id, "base", 29)
    target = _unit(tenant_id, "target", 29, rounding_mode=mode)
    service = UomConversionService()
    assert service.convert(Decimal("2.5E-29"), source, target).converted_amount == Decimal(
        positive + "E-29"
    )
    assert service.convert(Decimal("-2.5E-29"), source, target).converted_amount == Decimal(
        negative + "E-29"
    )


def test_unsupported_arithmetic_is_a_controlled_business_error() -> None:
    tenant_id = uuid4()
    source = _unit(tenant_id, "base", 2)
    target = _unit(tenant_id, "target", 100)
    service = UomConversionService()
    for amount in (Decimal("1E+1000"), Decimal("NaN")):
        with pytest.raises(BusinessOSError) as error:
            service.convert(amount, source, target)
        assert error.value.code == "uom_conversion_out_of_range"
    with pytest.raises(BusinessOSError):
        service.convert(Decimal("1"), source, target.model_copy(update={"rounding_mode": "BAD"}))
    with pytest.raises(BusinessOSError):
        service.convert(
            Decimal("1"), source, target.model_copy(update={"conversion_ratio": Decimal("0")})
        )
