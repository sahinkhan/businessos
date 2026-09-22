"""Geography and address foundation module registration and handlers."""

import json
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select

from businessos.sdk import (
    BusinessOSError,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import (
    AddressFormatProviderContract,
    AddressRecord,
    CityRecord,
    CountryRecord,
    SubdivisionRecord,
)
from .models import ADDRESSES, CITIES, COUNTRIES, SUBDIVISIONS


class RegisterCountry(Command):
    code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    alpha3_code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    numeric_code: str = Field(min_length=1, max_length=3)
    name: str = Field(min_length=1, max_length=200)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    phone_prefix: str | None = Field(default=None, max_length=10)
    address_format: dict[str, object] = Field(default_factory=dict)


class RegisterSubdivision(Command):
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=50)


class RegisterCity(Command):
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    name: str = Field(min_length=1, max_length=200)
    subdivision_id: UUID | None = None
    postal_code_pattern: str | None = Field(default=None, max_length=50)


class CreateAddress(Command):
    tenant_id: UUID
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    subdivision_code: str | None = Field(default=None, max_length=10)
    city: str = Field(min_length=1, max_length=200)
    postal_code: str | None = Field(default=None, max_length=30)
    street_line1: str = Field(min_length=1, max_length=300)
    street_line2: str | None = Field(default=None, max_length=300)
    coordinates: dict[str, float] | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class GetCountry(Query):
    code: str = Field(min_length=2, max_length=2)


class ListCountries(Query):
    active_only: bool = True


class GetSubdivision(Query):
    country_code: str
    code: str


class ListSubdivisions(Query):
    country_code: str


class GetAddress(Query):
    address_id: UUID


class CountryRegistered(DomainEvent):
    event_type: ClassVar[str] = "geography.country.registered.v1"
    country_code: str
    country_name: str


class AddressCreated(DomainEvent):
    event_type: ClassVar[str] = "geography.address.created.v1"
    address_id: UUID
    country_code: str
    city: str


class GeographyModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_geography").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.address_formatter = AddressFormatProviderContract()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.geography.read", description="Read geography and address data"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.geography.manage",
                description="Manage geography records and addresses",
            )
        )
        registration.contract("foundation.geography.address-formatter.v1", self.address_formatter)

        registration.command(
            RegisterCountry, self._register_country, permission="foundation.geography.manage"
        )
        registration.command(
            RegisterSubdivision,
            self._register_subdivision,
            permission="foundation.geography.manage",
        )
        registration.command(
            RegisterCity, self._register_city, permission="foundation.geography.manage"
        )
        registration.command(
            CreateAddress, self._create_address, permission="foundation.geography.manage"
        )

        registration.query(GetCountry, self._get_country, permission="foundation.geography.read")
        registration.query(
            ListCountries, self._list_countries, permission="foundation.geography.read"
        )
        registration.query(
            GetSubdivision, self._get_subdivision, permission="foundation.geography.read"
        )
        registration.query(
            ListSubdivisions, self._list_subdivisions, permission="foundation.geography.read"
        )
        registration.query(GetAddress, self._get_address, permission="foundation.geography.read")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _register_country(
        self, command: RegisterCountry, context: HandlingContext
    ) -> CountryRecord:
        tenant = _require_active_tenant(context.request)
        country_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(COUNTRIES).values(
                id=country_id,
                code=command.code,
                alpha3_code=command.alpha3_code,
                numeric_code=command.numeric_code,
                name=command.name,
                currency_code=command.currency_code,
                phone_prefix=command.phone_prefix,
                address_format=command.address_format,
                is_active=True,
            )
        )
        context.emit(
            CountryRegistered(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                country_code=command.code,
                country_name=command.name,
            )
        )
        return CountryRecord(
            id=country_id,
            code=command.code,
            alpha3_code=command.alpha3_code,
            numeric_code=command.numeric_code,
            name=command.name,
            currency_code=command.currency_code,
            phone_prefix=command.phone_prefix,
            address_format=command.address_format,
            is_active=True,
        )

    async def _register_subdivision(
        self, command: RegisterSubdivision, context: HandlingContext
    ) -> SubdivisionRecord:
        sub_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(SUBDIVISIONS).values(
                id=sub_id,
                country_code=command.country_code,
                code=command.code,
                name=command.name,
                category=command.category,
                is_active=True,
            )
        )
        return SubdivisionRecord(
            id=sub_id,
            country_code=command.country_code,
            code=command.code,
            name=command.name,
            category=command.category,
            is_active=True,
        )

    async def _register_city(self, command: RegisterCity, context: HandlingContext) -> CityRecord:
        country = await self._get_country(GetCountry(code=command.country_code), context)
        if country is None:
            raise BusinessOSError("not_found", "Country not found", status_code=404)
        if command.subdivision_id is not None:
            subdivision = (
                await context.unit_of_work.persistence.execute(
                    select(SUBDIVISIONS.c.id).where(
                        SUBDIVISIONS.c.id == command.subdivision_id,
                        SUBDIVISIONS.c.country_code == command.country_code,
                    )
                )
            ).first()
            if subdivision is None:
                raise BusinessOSError(
                    "invalid_subdivision", "Subdivision does not belong to country", status_code=400
                )
        city_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(CITIES).values(
                id=city_id,
                country_code=command.country_code,
                subdivision_id=command.subdivision_id,
                name=command.name,
                postal_code_pattern=command.postal_code_pattern,
                is_active=True,
            )
        )
        return CityRecord(
            id=city_id,
            country_code=command.country_code,
            subdivision_id=command.subdivision_id,
            name=command.name,
            postal_code_pattern=command.postal_code_pattern,
            is_active=True,
        )

    async def _create_address(
        self, command: CreateAddress, context: HandlingContext
    ) -> AddressRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        country = await self._get_country(GetCountry(code=command.country_code), context)
        if country is None:
            raise BusinessOSError("not_found", "Country not found", status_code=404)
        subdivision_id = None
        if command.subdivision_code is not None:
            subdivision = (
                await context.unit_of_work.persistence.execute(
                    select(SUBDIVISIONS.c.id).where(
                        SUBDIVISIONS.c.country_code == command.country_code,
                        SUBDIVISIONS.c.code == command.subdivision_code,
                    )
                )
            ).first()
            if subdivision is None:
                raise BusinessOSError(
                    "invalid_subdivision", "Subdivision does not belong to country", status_code=400
                )
            subdivision_id = subdivision.id
        city = (
            await context.unit_of_work.persistence.execute(
                select(CITIES.c.id).where(
                    CITIES.c.country_code == command.country_code,
                    CITIES.c.name == command.city,
                    *(
                        (CITIES.c.subdivision_id == subdivision_id,)
                        if subdivision_id is not None
                        else ()
                    ),
                )
            )
        ).first()
        if city is None:
            raise BusinessOSError(
                "invalid_city", "City does not belong to address parent", status_code=400
            )
        formatted = self.address_formatter.format(
            street_line1=command.street_line1,
            street_line2=command.street_line2,
            city=command.city,
            subdivision_code=command.subdivision_code,
            postal_code=command.postal_code,
            country_code=command.country_code,
        )
        addr_id = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(ADDRESSES)
            .values(
                id=addr_id,
                tenant_id=tenant.tenant_id,
                country_code=command.country_code,
                subdivision_code=command.subdivision_code,
                city=command.city,
                postal_code=command.postal_code,
                street_line1=command.street_line1,
                street_line2=command.street_line2,
                formatted_address=formatted,
                coordinates=command.coordinates,
                metadata=command.metadata,
            )
            .returning(ADDRESSES.c.created_at)
        )
        row = res.first()
        if row is None:
            raise RuntimeError("Address insert did not return its database timestamp")
        created_at = row[0]

        context.emit(
            AddressCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                address_id=addr_id,
                country_code=command.country_code,
                city=command.city,
            )
        )
        return AddressRecord(
            id=addr_id,
            tenant_id=tenant.tenant_id,
            country_code=command.country_code,
            subdivision_code=command.subdivision_code,
            city=command.city,
            postal_code=command.postal_code,
            street_line1=command.street_line1,
            street_line2=command.street_line2,
            formatted_address=formatted,
            coordinates=command.coordinates,
            metadata=command.metadata,
            created_at=created_at,
        )

    async def _get_country(
        self, query: GetCountry, context: HandlingContext
    ) -> CountryRecord | None:
        stmt = select(COUNTRIES).where(COUNTRIES.c.code == query.code)
        result = await context.unit_of_work.persistence.execute(stmt)
        row = result.first()
        if not row:
            return None
        return CountryRecord(
            id=row.id,
            code=row.code,
            alpha3_code=row.alpha3_code,
            numeric_code=row.numeric_code,
            name=row.name,
            currency_code=row.currency_code,
            phone_prefix=row.phone_prefix,
            address_format=row.address_format,
            is_active=row.is_active,
        )

    async def _list_countries(
        self, query: ListCountries, context: HandlingContext
    ) -> list[CountryRecord]:
        stmt = select(COUNTRIES)
        if query.active_only:
            stmt = stmt.where(COUNTRIES.c.is_active.is_(True))
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            CountryRecord(
                id=row.id,
                code=row.code,
                alpha3_code=row.alpha3_code,
                numeric_code=row.numeric_code,
                name=row.name,
                currency_code=row.currency_code,
                phone_prefix=row.phone_prefix,
                address_format=row.address_format,
                is_active=row.is_active,
            )
            for row in result.fetchall()
        ]

    async def _get_subdivision(
        self, query: GetSubdivision, context: HandlingContext
    ) -> SubdivisionRecord | None:
        stmt = select(SUBDIVISIONS).where(
            SUBDIVISIONS.c.country_code == query.country_code,
            SUBDIVISIONS.c.code == query.code,
        )
        result = await context.unit_of_work.persistence.execute(stmt)
        row = result.first()
        if not row:
            return None
        return SubdivisionRecord(
            id=row.id,
            country_code=row.country_code,
            code=row.code,
            name=row.name,
            category=row.category,
            is_active=row.is_active,
        )

    async def _list_subdivisions(
        self, query: ListSubdivisions, context: HandlingContext
    ) -> list[SubdivisionRecord]:
        stmt = select(SUBDIVISIONS).where(SUBDIVISIONS.c.country_code == query.country_code)
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            SubdivisionRecord(
                id=row.id,
                country_code=row.country_code,
                code=row.code,
                name=row.name,
                category=row.category,
                is_active=row.is_active,
            )
            for row in result.fetchall()
        ]

    async def _get_address(
        self, query: GetAddress, context: HandlingContext
    ) -> AddressRecord | None:
        stmt = select(ADDRESSES).where(ADDRESSES.c.id == query.address_id)
        result = await context.unit_of_work.persistence.execute(stmt)
        row = result.first()
        if not row:
            return None
        return AddressRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            country_code=row.country_code,
            subdivision_code=row.subdivision_code,
            city=row.city,
            postal_code=row.postal_code,
            street_line1=row.street_line1,
            street_line2=row.street_line2,
            formatted_address=row.formatted_address,
            coordinates=row.coordinates,
            metadata=row.metadata,
            created_at=row.created_at,
        )


def _require_tenant(request: RequestContext | None, target_tenant_id: UUID) -> TenantContext:
    tenant = _require_active_tenant(request)
    if tenant.tenant_id != target_tenant_id:
        raise BusinessOSError(
            "tenant_scope_mismatch",
            "Target tenant does not match active boundary",
            status_code=403,
        )
    return tenant


def _require_active_tenant(request: RequestContext | None) -> TenantContext:
    if request is None or request.tenant is None:
        raise BusinessOSError(
            "tenant_context_required",
            "Tenant context is required",
            status_code=400,
        )
    return request.tenant
