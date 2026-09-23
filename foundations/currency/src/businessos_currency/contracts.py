"""Typed public contracts for canonical Currency master data."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CurrencyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    numeric_code: str | None
    name: str
    minor_unit: int
    is_active: bool
    source: str
    source_version: int


class CurrencyReadContract:
    """Marker for the versioned Currency read surface."""

    version: str = "1.0"
