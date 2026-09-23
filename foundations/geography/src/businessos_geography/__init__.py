"""Geography and address foundation module."""

from .contracts import (
    AddressFormatProviderContract,
    AddressRecord,
    AddressValidationError,
    AddressValidationProviderContract,
    AddressValidationResult,
    CityRecord,
    CountryRecord,
    SubdivisionRecord,
)
from .models import ADDRESSES, CITIES, COUNTRIES, SUBDIVISIONS, metadata
from .module import (
    AddressCreated,
    CreateAddress,
    GeographyModule,
    GetAddress,
    GetCountry,
    GetSubdivision,
    ListCountries,
    ListSubdivisions,
    RegisterCity,
    RegisterCountry,
    RegisterSubdivision,
    ValidateAddress,
)
from .module import (
    CountryRegistered as CountryRegistered,
)

__all__ = [
    "ADDRESSES",
    "CITIES",
    "COUNTRIES",
    "SUBDIVISIONS",
    "AddressCreated",
    "AddressFormatProviderContract",
    "AddressRecord",
    "AddressValidationError",
    "AddressValidationProviderContract",
    "AddressValidationResult",
    "CityRecord",
    "CountryRecord",
    "CreateAddress",
    "GeographyModule",
    "GetAddress",
    "GetCountry",
    "GetSubdivision",
    "ListCountries",
    "ListSubdivisions",
    "RegisterCity",
    "RegisterCountry",
    "RegisterSubdivision",
    "SubdivisionRecord",
    "ValidateAddress",
    "metadata",
]
