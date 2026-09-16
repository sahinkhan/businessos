"""Domain and application contracts for the geography foundation."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CountryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    alpha3_code: str
    numeric_code: str
    name: str
    currency_code: str | None = None
    phone_prefix: str | None = None
    address_format: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class SubdivisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    country_code: str
    code: str
    name: str
    category: str
    is_active: bool = True


class CityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    country_code: str
    subdivision_id: UUID | None = None
    name: str
    postal_code_pattern: str | None = None
    is_active: bool = True


class AddressRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    country_code: str
    subdivision_code: str | None = None
    city: str
    postal_code: str | None = None
    street_line1: str
    street_line2: str | None = None
    formatted_address: str
    coordinates: dict[str, float] | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AddressFormatProviderContract:
    """Format an address based on country-specific rules."""

    def format(
        self,
        street_line1: str,
        city: str,
        country_code: str,
        street_line2: str | None = None,
        subdivision_code: str | None = None,
        postal_code: str | None = None,
    ) -> str:
        lines: list[str] = [street_line1]
        if street_line2:
            lines.append(street_line2)
        locality_parts: list[str] = []
        if city:
            locality_parts.append(city)
        if subdivision_code:
            locality_parts.append(subdivision_code)
        if postal_code:
            locality_parts.append(postal_code)
        if locality_parts:
            lines.append(" ".join(locality_parts))
        lines.append(country_code.upper())
        return "\n".join(lines)
