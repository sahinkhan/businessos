"""Reference data and number sequence foundation module registration and handlers."""

import json
from datetime import datetime
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select, update

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
    GeneratedNumberRecord,
    NumberSequenceRecord,
    ReferenceSetRecord,
    ReferenceValueRecord,
)
from .models import NUMBER_SEQUENCES, REFERENCE_SETS, REFERENCE_VALUES


class RegisterReferenceSet(Command):
    tenant_id: UUID
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    owning_module: str = Field(min_length=1, max_length=100)
    is_extensible: bool = True
    is_system: bool = False


class CreateReferenceValue(Command):
    tenant_id: UUID
    set_code: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=100)
    label_key: str = Field(min_length=1, max_length=200)
    default_label: str = Field(min_length=1, max_length=200)
    description: str | None = None
    external_id: str | None = None
    sort_order: int = 0
    seed_version: int = 1
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    properties: dict[str, object] = Field(default_factory=dict)


class ConfigureNumberSequence(Command):
    tenant_id: UUID
    code: str = Field(min_length=1, max_length=100)
    prefix: str = Field(default="", max_length=30)
    suffix: str = Field(default="", max_length=30)
    next_value: int = Field(default=1, ge=1)
    step: int = Field(default=1, ge=1)
    padding: int = Field(default=6, ge=1, le=20)


class GenerateNextNumber(Command):
    tenant_id: UUID
    code: str = Field(min_length=1, max_length=100)


class GetReferenceSet(Query):
    tenant_id: UUID
    code: str


class ListReferenceSets(Query):
    tenant_id: UUID
    owning_module: str | None = None


class GetReferenceValue(Query):
    tenant_id: UUID
    set_code: str
    code: str


class ListReferenceValues(Query):
    tenant_id: UUID
    set_code: str
    active_only: bool = True


class ResolveReferenceValueByExternalId(Query):
    tenant_id: UUID
    set_code: str
    external_id: str


class ReferenceSetRegistered(DomainEvent):
    event_type: ClassVar[str] = "reference_data.set.registered.v1"
    set_code: str
    owning_module: str


class ReferenceValueChanged(DomainEvent):
    event_type: ClassVar[str] = "reference_data.value.changed.v1"
    set_code: str
    value_code: str
    label: str


class ReferenceDataModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_reference_data").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.reference_data.read", description="Read reference data"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.reference_data.manage",
                description="Manage reference data and sequences",
            )
        )

        registration.command(
            RegisterReferenceSet, self._register_set, permission="foundation.reference_data.manage"
        )
        registration.command(
            CreateReferenceValue, self._create_value, permission="foundation.reference_data.manage"
        )
        registration.command(
            ConfigureNumberSequence,
            self._configure_sequence,
            permission="foundation.reference_data.manage",
        )
        registration.command(
            GenerateNextNumber, self._generate_number, permission="foundation.reference_data.manage"
        )

        registration.query(
            GetReferenceSet, self._get_set, permission="foundation.reference_data.read"
        )
        registration.query(
            ListReferenceSets, self._list_sets, permission="foundation.reference_data.read"
        )
        registration.query(
            GetReferenceValue, self._get_value, permission="foundation.reference_data.read"
        )
        registration.query(
            ListReferenceValues, self._list_values, permission="foundation.reference_data.read"
        )
        registration.query(
            ResolveReferenceValueByExternalId,
            self._resolve_by_external_id,
            permission="foundation.reference_data.read",
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _register_set(
        self, command: RegisterReferenceSet, context: HandlingContext
    ) -> ReferenceSetRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        set_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(REFERENCE_SETS).values(
                id=set_id,
                tenant_id=tenant.tenant_id,
                code=command.code,
                name=command.name,
                description=command.description,
                owning_module=command.owning_module,
                is_extensible=command.is_extensible,
                is_system=command.is_system,
                is_active=True,
            )
        )
        context.emit(
            ReferenceSetRegistered(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                set_code=command.code,
                owning_module=command.owning_module,
            )
        )
        return ReferenceSetRecord(
            id=set_id,
            tenant_id=tenant.tenant_id,
            code=command.code,
            name=command.name,
            description=command.description,
            owning_module=command.owning_module,
            is_extensible=command.is_extensible,
            is_system=command.is_system,
            is_active=True,
            created_at=datetime.now(),
        )

    async def _create_value(
        self, command: CreateReferenceValue, context: HandlingContext
    ) -> ReferenceValueRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        val_id = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(REFERENCE_VALUES)
            .values(
                id=val_id,
                tenant_id=tenant.tenant_id,
                set_code=command.set_code,
                code=command.code,
                label_key=command.label_key,
                default_label=command.default_label,
                description=command.description,
                external_id=command.external_id,
                sort_order=command.sort_order,
                seed_version=command.seed_version,
                effective_from=command.effective_from,
                effective_until=command.effective_until,
                is_active=True,
                properties=command.properties,
            )
            .returning(REFERENCE_VALUES.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()

        context.emit(
            ReferenceValueChanged(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                set_code=command.set_code,
                value_code=command.code,
                label=command.default_label,
            )
        )
        return ReferenceValueRecord(
            id=val_id,
            tenant_id=tenant.tenant_id,
            set_code=command.set_code,
            code=command.code,
            label_key=command.label_key,
            default_label=command.default_label,
            description=command.description,
            external_id=command.external_id,
            sort_order=command.sort_order,
            seed_version=command.seed_version,
            effective_from=command.effective_from,
            effective_until=command.effective_until,
            is_active=True,
            properties=command.properties,
            created_at=created_at,
        )

    async def _configure_sequence(
        self, command: ConfigureNumberSequence, context: HandlingContext
    ) -> NumberSequenceRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        seq_id = uuid4()
        stmt = select(NUMBER_SEQUENCES).where(
            NUMBER_SEQUENCES.c.tenant_id == tenant.tenant_id,
            NUMBER_SEQUENCES.c.code == command.code,
        )
        existing = (await context.unit_of_work.persistence.execute(stmt)).first()
        if existing:
            await context.unit_of_work.persistence.execute(
                update(NUMBER_SEQUENCES)
                .where(
                    NUMBER_SEQUENCES.c.tenant_id == tenant.tenant_id,
                    NUMBER_SEQUENCES.c.code == command.code,
                )
                .values(
                    prefix=command.prefix,
                    suffix=command.suffix,
                    next_value=command.next_value,
                    step=command.step,
                    padding=command.padding,
                )
            )
            return NumberSequenceRecord(
                id=existing.id,
                tenant_id=tenant.tenant_id,
                code=command.code,
                prefix=command.prefix,
                suffix=command.suffix,
                next_value=command.next_value,
                step=command.step,
                padding=command.padding,
                is_active=existing.is_active,
            )

        await context.unit_of_work.persistence.execute(
            insert(NUMBER_SEQUENCES).values(
                id=seq_id,
                tenant_id=tenant.tenant_id,
                code=command.code,
                prefix=command.prefix,
                suffix=command.suffix,
                next_value=command.next_value,
                step=command.step,
                padding=command.padding,
                is_active=True,
            )
        )
        return NumberSequenceRecord(
            id=seq_id,
            tenant_id=tenant.tenant_id,
            code=command.code,
            prefix=command.prefix,
            suffix=command.suffix,
            next_value=command.next_value,
            step=command.step,
            padding=command.padding,
            is_active=True,
        )

    async def _generate_number(
        self, command: GenerateNextNumber, context: HandlingContext
    ) -> GeneratedNumberRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        stmt = (
            select(NUMBER_SEQUENCES)
            .where(
                NUMBER_SEQUENCES.c.tenant_id == tenant.tenant_id,
                NUMBER_SEQUENCES.c.code == command.code,
            )
            .with_for_update()
        )
        result = await context.unit_of_work.persistence.execute(stmt)
        row = result.first()
        if not row:
            # initialize default sequence
            seq_id = uuid4()
            current_val = 1
            await context.unit_of_work.persistence.execute(
                insert(NUMBER_SEQUENCES).values(
                    id=seq_id,
                    tenant_id=tenant.tenant_id,
                    code=command.code,
                    prefix="",
                    suffix="",
                    next_value=2,
                    step=1,
                    padding=6,
                    is_active=True,
                )
            )
            formatted = str(current_val).zfill(6)
            return GeneratedNumberRecord(
                sequence_code=command.code,
                formatted_number=formatted,
                numeric_value=current_val,
            )

        current_val = row.next_value
        next_val = current_val + row.step
        await context.unit_of_work.persistence.execute(
            update(NUMBER_SEQUENCES)
            .where(
                NUMBER_SEQUENCES.c.tenant_id == tenant.tenant_id,
                NUMBER_SEQUENCES.c.code == command.code,
            )
            .values(next_value=next_val)
        )
        num_str = str(current_val).zfill(row.padding)
        formatted = f"{row.prefix}{num_str}{row.suffix}"
        return GeneratedNumberRecord(
            sequence_code=command.code,
            formatted_number=formatted,
            numeric_value=current_val,
        )

    async def _get_set(
        self, query: GetReferenceSet, context: HandlingContext
    ) -> ReferenceSetRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(REFERENCE_SETS).where(
            REFERENCE_SETS.c.tenant_id == tenant.tenant_id,
            REFERENCE_SETS.c.code == query.code,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return ReferenceSetRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            code=row.code,
            name=row.name,
            description=row.description,
            owning_module=row.owning_module,
            is_extensible=row.is_extensible,
            is_system=row.is_system,
            is_active=row.is_active,
            created_at=row.created_at,
        )

    async def _list_sets(
        self, query: ListReferenceSets, context: HandlingContext
    ) -> list[ReferenceSetRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(REFERENCE_SETS).where(REFERENCE_SETS.c.tenant_id == tenant.tenant_id)
        if query.owning_module:
            stmt = stmt.where(REFERENCE_SETS.c.owning_module == query.owning_module)
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            ReferenceSetRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                code=row.code,
                name=row.name,
                description=row.description,
                owning_module=row.owning_module,
                is_extensible=row.is_extensible,
                is_system=row.is_system,
                is_active=row.is_active,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]

    async def _get_value(
        self, query: GetReferenceValue, context: HandlingContext
    ) -> ReferenceValueRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(REFERENCE_VALUES).where(
            REFERENCE_VALUES.c.tenant_id == tenant.tenant_id,
            REFERENCE_VALUES.c.set_code == query.set_code,
            REFERENCE_VALUES.c.code == query.code,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return ReferenceValueRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            set_code=row.set_code,
            code=row.code,
            label_key=row.label_key,
            default_label=row.default_label,
            description=row.description,
            external_id=row.external_id,
            sort_order=row.sort_order,
            seed_version=row.seed_version,
            effective_from=row.effective_from,
            effective_until=row.effective_until,
            is_active=row.is_active,
            properties=row.properties,
            created_at=row.created_at,
        )

    async def _list_values(
        self, query: ListReferenceValues, context: HandlingContext
    ) -> list[ReferenceValueRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(REFERENCE_VALUES).where(
            REFERENCE_VALUES.c.tenant_id == tenant.tenant_id,
            REFERENCE_VALUES.c.set_code == query.set_code,
        )
        if query.active_only:
            stmt = stmt.where(REFERENCE_VALUES.c.is_active.is_(True))
        stmt = stmt.order_by(REFERENCE_VALUES.c.sort_order, REFERENCE_VALUES.c.code)
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            ReferenceValueRecord(
                id=row.id,
                tenant_id=row.tenant_id,
                set_code=row.set_code,
                code=row.code,
                label_key=row.label_key,
                default_label=row.default_label,
                description=row.description,
                external_id=row.external_id,
                sort_order=row.sort_order,
                seed_version=row.seed_version,
                effective_from=row.effective_from,
                effective_until=row.effective_until,
                is_active=row.is_active,
                properties=row.properties,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]

    async def _resolve_by_external_id(
        self, query: ResolveReferenceValueByExternalId, context: HandlingContext
    ) -> ReferenceValueRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(REFERENCE_VALUES).where(
            REFERENCE_VALUES.c.tenant_id == tenant.tenant_id,
            REFERENCE_VALUES.c.set_code == query.set_code,
            REFERENCE_VALUES.c.external_id == query.external_id,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return ReferenceValueRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            set_code=row.set_code,
            code=row.code,
            label_key=row.label_key,
            default_label=row.default_label,
            description=row.description,
            external_id=row.external_id,
            sort_order=row.sort_order,
            seed_version=row.seed_version,
            effective_from=row.effective_from,
            effective_until=row.effective_until,
            is_active=row.is_active,
            properties=row.properties,
            created_at=row.created_at,
        )


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
