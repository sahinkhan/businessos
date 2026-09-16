"""Domain and application contracts for the unit of measure foundation."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from uuid import UUID
from pydantic import BaseModel, ConfigDict


_ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
}


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
    precision: int = 2
    rounding_mode: str = "ROUND_HALF_UP"
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

    def convert(
        self,
        amount: Decimal | float | str,
        from_unit: UnitOfMeasureRecord,
        to_unit: UnitOfMeasureRecord,
    ) -> ConvertedAmountRecord:
        if from_unit.category_code != to_unit.category_code:
            raise ValueError(
                f"Cannot convert between different categories: '{from_unit.category_code}' and '{to_unit.category_code}'"
            )

        amt = Decimal(str(amount))

        # 1. Convert from_unit to base unit:
        # base_value = (amt * from_unit.conversion_ratio) + from_unit.conversion_offset
        base_value = (amt * from_unit.conversion_ratio) + from_unit.conversion_offset

        # 2. Convert base unit to to_unit:
        # target_value = (base_value - to_unit.conversion_offset) / to_unit.conversion_ratio
        target_value = (base_value - to_unit.conversion_offset) / to_unit.conversion_ratio

        # 3. Apply precision & rounding mode
        rounding = _ROUNDING_MODES.get(to_unit.rounding_mode, ROUND_HALF_UP)
        quantizer = Decimal("10") ** -to_unit.precision if to_unit.precision > 0 else Decimal("1")
        final_amt = target_value.quantize(quantizer, rounding=rounding)

        return ConvertedAmountRecord(
            from_unit=from_unit.code,
            to_unit=to_unit.code,
            original_amount=amt,
            converted_amount=final_amt,
            precision=to_unit.precision,
        )
