"""Domain and application contracts for the unit of measure foundation."""

from datetime import datetime
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from businessos.sdk import BusinessOSError

MAX_UOM_DECIMAL_PLACES = 100
MAX_UOM_CONTEXT_DIGITS = 512
_MIN_DIVISION_GUARD_DIGITS = 16

_ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
}
RoundingMode = Literal[
    "ROUND_HALF_UP",
    "ROUND_HALF_EVEN",
    "ROUND_FLOOR",
    "ROUND_CEILING",
    "ROUND_UP",
    "ROUND_DOWN",
]


class MeasurementCategoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    description: str | None = None
    base_unit_code: str
    is_active: bool = True
    created_at: datetime


class UnitOfMeasureRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    category_code: str
    code: str
    name: str
    symbol: str
    is_base_unit: bool = False
    conversion_ratio: Decimal
    conversion_offset: Decimal = Decimal("0")
    precision: int = Field(default=2, ge=0, le=MAX_UOM_DECIMAL_PLACES)
    rounding_mode: RoundingMode = "ROUND_HALF_UP"
    is_active: bool = True
    created_at: datetime


class ConvertedAmountRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_unit: str
    to_unit: str
    original_amount: Decimal
    converted_amount: Decimal
    precision: int


class UomConversionService:
    """Accurate UoM conversion using exact Decimal arithmetic and rounding."""

    version: str = "1.0"

    def convert(
        self,
        amount: Decimal | float | str,
        from_unit: UnitOfMeasureRecord,
        to_unit: UnitOfMeasureRecord,
    ) -> ConvertedAmountRecord:
        if from_unit.tenant_id != to_unit.tenant_id:
            raise ValueError("Cannot convert units owned by different tenants")
        if from_unit.category_code != to_unit.category_code:
            raise ValueError(
                f"Cannot convert between different categories: '{from_unit.category_code}' "
                f"and '{to_unit.category_code}'"
            )

        try:
            amt = Decimal(str(amount))
        except InvalidOperation as exc:
            raise _conversion_error() from exc
        operands = (
            amt,
            from_unit.conversion_ratio,
            from_unit.conversion_offset,
            to_unit.conversion_ratio,
            to_unit.conversion_offset,
        )
        if (
            not all(value.is_finite() for value in operands)
            or from_unit.conversion_ratio <= 0
            or to_unit.conversion_ratio <= 0
            or not 0 <= to_unit.precision <= MAX_UOM_DECIMAL_PLACES
        ):
            raise _conversion_error()
        rounding = _ROUNDING_MODES.get(to_unit.rounding_mode)
        if rounding is None:
            raise _conversion_error()

        capacity = _conversion_context_digits(*operands, to_unit.precision)
        if capacity > MAX_UOM_CONTEXT_DIGITS:
            raise _conversion_error()
        quantizer = Decimal((0, (1,), -to_unit.precision))
        try:
            # A fresh local context avoids the process default's 28-digit limit
            # and makes intermediate division independent of caller state.
            with localcontext(Context(prec=capacity)):
                base_value = amt * from_unit.conversion_ratio + from_unit.conversion_offset
                target_value = (base_value - to_unit.conversion_offset) / to_unit.conversion_ratio
                final_amt = target_value.quantize(quantizer, rounding=rounding)
        except (InvalidOperation, DivisionByZero, Overflow) as exc:
            raise _conversion_error() from exc

        return ConvertedAmountRecord(
            from_unit=from_unit.code,
            to_unit=to_unit.code,
            original_amount=amt,
            converted_amount=final_amt,
            precision=to_unit.precision,
        )


def _integer_digits(value: Decimal) -> int:
    return max(1, value.adjusted() + 1)


def _fractional_digits(value: Decimal) -> int:
    return max(0, -int(value.as_tuple().exponent))


def _conversion_context_digits(
    amount: Decimal,
    from_ratio: Decimal,
    from_offset: Decimal,
    to_ratio: Decimal,
    to_offset: Decimal,
    places: int,
) -> int:
    # Bound exact multiply/add/subtract work and leave enough quotient digits
    # for its integer magnitude, requested output scale, and division guard.
    product_integer = _integer_digits(amount) + _integer_digits(from_ratio) + 1
    product_fraction = _fractional_digits(amount) + _fractional_digits(from_ratio)
    base_integer = max(product_integer, _integer_digits(from_offset)) + 1
    base_fraction = max(product_fraction, _fractional_digits(from_offset))
    numerator_integer = max(base_integer, _integer_digits(to_offset)) + 1
    numerator_fraction = max(base_fraction, _fractional_digits(to_offset))
    quotient_integer = max(1, numerator_integer - to_ratio.adjusted() + 1)
    # A quotient can sit arbitrarily close to a rounding tie. The divisor's
    # finite coefficient bounds how many extra digits distinguish that tie.
    division_guard = max(_MIN_DIVISION_GUARD_DIGITS, len(to_ratio.as_tuple().digits) + 2)
    return max(
        28,
        product_integer + product_fraction,
        base_integer + base_fraction,
        numerator_integer + numerator_fraction,
        quotient_integer + places + division_guard,
    )


def _conversion_error() -> BusinessOSError:
    return BusinessOSError(
        "uom_conversion_out_of_range",
        "UoM conversion exceeds the supported numeric range",
        status_code=422,
    )
