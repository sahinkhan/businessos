"""Units of measure foundation module registration and handlers."""

import json
from datetime import datetime
from decimal import Decimal
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
    MAX_UOM_DECIMAL_PLACES,
    ConvertedAmountRecord,
    MeasurementCategoryRecord,
    RoundingMode,
    UnitOfMeasureRecord,
    UomConversionService,
)
from .models import MEASUREMENT_CATEGORIES, UNITS_OF_MEASURE


class CreateMeasurementCategory(Command):
    tenant_id: UUID
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    base_unit_code: str = Field(min_length=1, max_length=50)


class CreateUnitOfMeasure(Command):
    tenant_id: UUID
    category_code: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=20)
    is_base_unit: bool = False
    conversion_ratio: Decimal = Field(default=Decimal("1.0"), gt=0)
    conversion_offset: Decimal = Field(default=Decimal("0.0"))
    precision: int = Field(default=2, ge=0, le=MAX_UOM_DECIMAL_PLACES)
    rounding_mode: RoundingMode = "ROUND_HALF_UP"


class ConvertQuantity(Command):
    tenant_id: UUID
    from_unit_code: str = Field(min_length=1, max_length=50)
    to_unit_code: str = Field(min_length=1, max_length=50)
    amount: Decimal


class GetMeasurementCategory(Query):
    tenant_id: UUID
    code: str


class ListMeasurementCategories(Query):
    tenant_id: UUID
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GetUnitOfMeasure(Query):
    tenant_id: UUID
    code: str


class ListUnitsOfMeasure(Query):
    tenant_id: UUID
    category_code: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class UomCategoryCreated(DomainEvent):
    event_type: ClassVar[str] = "uom.category.created.v1"
    code: str
    base_unit_code: str


class UomUnitChanged(DomainEvent):
    event_type: ClassVar[str] = "uom.unit.changed.v1"
    unit_code: str
    category_code: str


class UomModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_uom").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.conversion_service = UomConversionService()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(key="foundation.uom.read", description="Read units of measure")
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.uom.manage", description="Manage units of measure"
            )
        )
        registration.contract("foundation.uom.conversion-service.v1", self.conversion_service)

        registration.command(
            CreateMeasurementCategory, self._create_category, permission="foundation.uom.manage"
        )
        registration.command(
            CreateUnitOfMeasure, self._create_unit, permission="foundation.uom.manage"
        )
        registration.command(
            ConvertQuantity, self._convert_quantity, permission="foundation.uom.read"
        )

        registration.query(
            GetMeasurementCategory, self._get_category, permission="foundation.uom.read"
        )
        registration.query(
            ListMeasurementCategories, self._list_categories, permission="foundation.uom.read"
        )
        registration.query(GetUnitOfMeasure, self._get_unit, permission="foundation.uom.read")
        registration.query(ListUnitsOfMeasure, self._list_units, permission="foundation.uom.read")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _create_category(
        self, command: CreateMeasurementCategory, context: HandlingContext
    ) -> MeasurementCategoryRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        cat_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(MEASUREMENT_CATEGORIES).values(
                id=cat_id,
                tenant_id=tenant.tenant_id,
                code=command.code,
                name=command.name,
                description=command.description,
                base_unit_code=command.base_unit_code,
                is_active=True,
            )
        )
        context.emit(
            UomCategoryCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                code=command.code,
                base_unit_code=command.base_unit_code,
            )
        )
        return MeasurementCategoryRecord(
            id=cat_id,
            tenant_id=tenant.tenant_id,
            code=command.code,
            name=command.name,
            description=command.description,
            base_unit_code=command.base_unit_code,
            is_active=True,
            created_at=datetime.now(),
        )

    async def _create_unit(
        self, command: CreateUnitOfMeasure, context: HandlingContext
    ) -> UnitOfMeasureRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        category = await self._get_category(
            GetMeasurementCategory(tenant_id=tenant.tenant_id, code=command.category_code),
            context,
        )
        if category is None:
            raise BusinessOSError("not_found", "Measurement category not found", status_code=404)
        if command.is_base_unit != (command.code == category.base_unit_code):
            raise BusinessOSError(
                "invalid_base_unit", "Unit conflicts with category base unit", status_code=400
            )
        if command.is_base_unit and (
            command.conversion_ratio != Decimal("1") or command.conversion_offset != Decimal("0")
        ):
            raise BusinessOSError(
                "invalid_base_unit", "Base unit must use identity conversion", status_code=400
            )
        if not command.is_base_unit:
            base = await self._get_unit(
                GetUnitOfMeasure(tenant_id=tenant.tenant_id, code=category.base_unit_code),
                context,
            )
            if base is None or base.category_code != category.code or not base.is_base_unit:
                raise BusinessOSError(
                    "invalid_base_unit", "Category base unit must be created first", status_code=400
                )
        unit_id = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(UNITS_OF_MEASURE)
            .values(
                id=unit_id,
                tenant_id=tenant.tenant_id,
                category_code=command.category_code,
                code=command.code,
                name=command.name,
                symbol=command.symbol,
                is_base_unit=command.is_base_unit,
                conversion_ratio=command.conversion_ratio,
                conversion_offset=command.conversion_offset,
                precision=command.precision,
                rounding_mode=command.rounding_mode,
                is_active=True,
            )
            .returning(UNITS_OF_MEASURE.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()

        context.emit(
            UomUnitChanged(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                unit_code=command.code,
                category_code=command.category_code,
            )
        )
        return UnitOfMeasureRecord(
            id=unit_id,
            tenant_id=tenant.tenant_id,
            category_code=command.category_code,
            code=command.code,
            name=command.name,
            symbol=command.symbol,
            is_base_unit=command.is_base_unit,
            conversion_ratio=command.conversion_ratio,
            conversion_offset=command.conversion_offset,
            precision=command.precision,
            rounding_mode=command.rounding_mode,
            is_active=True,
            created_at=created_at,
        )

    async def _convert_quantity(
        self, command: ConvertQuantity, context: HandlingContext
    ) -> ConvertedAmountRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        u1 = await self._get_unit(
            GetUnitOfMeasure(tenant_id=tenant.tenant_id, code=command.from_unit_code), context
        )
        if not u1:
            raise BusinessOSError(
                "not_found",
                f"Source unit not found: {command.from_unit_code}",
                status_code=404,
            )
        u2 = await self._get_unit(
            GetUnitOfMeasure(tenant_id=tenant.tenant_id, code=command.to_unit_code), context
        )
        if not u2:
            raise BusinessOSError(
                "not_found",
                f"Target unit not found: {command.to_unit_code}",
                status_code=404,
            )

        return self.conversion_service.convert(command.amount, u1, u2)

    async def _get_category(
        self, query: GetMeasurementCategory, context: HandlingContext
    ) -> MeasurementCategoryRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(MEASUREMENT_CATEGORIES).where(
            MEASUREMENT_CATEGORIES.c.tenant_id == tenant.tenant_id,
            MEASUREMENT_CATEGORIES.c.code == query.code,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return MeasurementCategoryRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            code=row.code,
            name=row.name,
            description=row.description,
            base_unit_code=row.base_unit_code,
            is_active=row.is_active,
            created_at=row.created_at,
        )

    async def _list_categories(
        self, query: ListMeasurementCategories, context: HandlingContext
    ) -> list[MeasurementCategoryRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = (
            select(MEASUREMENT_CATEGORIES)
            .where(MEASUREMENT_CATEGORIES.c.tenant_id == tenant.tenant_id)
            .order_by(MEASUREMENT_CATEGORIES.c.code, MEASUREMENT_CATEGORIES.c.id)
            .limit(query.limit)
            .offset(query.offset)
        )
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            MeasurementCategoryRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                code=row.code,
                name=row.name,
                description=row.description,
                base_unit_code=row.base_unit_code,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]

    async def _get_unit(
        self, query: GetUnitOfMeasure, context: HandlingContext
    ) -> UnitOfMeasureRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(UNITS_OF_MEASURE).where(
            UNITS_OF_MEASURE.c.tenant_id == tenant.tenant_id,
            UNITS_OF_MEASURE.c.code == query.code,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return UnitOfMeasureRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            category_code=row.category_code,
            code=row.code,
            name=row.name,
            symbol=row.symbol,
            is_base_unit=row.is_base_unit,
            conversion_ratio=row.conversion_ratio,
            conversion_offset=row.conversion_offset,
            precision=row.precision,
            rounding_mode=row.rounding_mode,
            is_active=row.is_active,
            created_at=row.created_at,
        )

    async def _list_units(
        self, query: ListUnitsOfMeasure, context: HandlingContext
    ) -> list[UnitOfMeasureRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(UNITS_OF_MEASURE).where(UNITS_OF_MEASURE.c.tenant_id == tenant.tenant_id)
        if query.category_code:
            stmt = stmt.where(UNITS_OF_MEASURE.c.category_code == query.category_code)
        stmt = (
            stmt.order_by(UNITS_OF_MEASURE.c.code, UNITS_OF_MEASURE.c.id)
            .limit(query.limit)
            .offset(query.offset)
        )
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            UnitOfMeasureRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                category_code=row.category_code,
                code=row.code,
                name=row.name,
                symbol=row.symbol,
                is_base_unit=row.is_base_unit,
                conversion_ratio=row.conversion_ratio,
                conversion_offset=row.conversion_offset,
                precision=row.precision,
                rounding_mode=row.rounding_mode,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]


def _require_tenant(request: RequestContext | None, target_tenant_id: UUID) -> TenantContext:
    if request is None or request.tenant is None:
        raise BusinessOSError(
            "tenant_context_required",
            "Tenant context is required",
            status_code=400,
        )
    if request.tenant.tenant_id != target_tenant_id:
        raise BusinessOSError(
            "tenant_scope_mismatch",
            "Target tenant does not match active boundary",
            status_code=403,
        )
    return request.tenant
