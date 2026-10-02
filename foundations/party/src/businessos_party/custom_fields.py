"""Party-root custom values: owner admission, lifecycle locks and one owner UOW."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import ClassVar, Self, cast
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, StrictInt, model_validator
from sqlalchemy import Insert, Update, insert, select, update

from businessos.sdk import (
    PUBLISHED_CUSTOM_FIELD_SCHEMA,
    RESOURCE_OWNER_RESOLVER,
    BusinessOSError,
    Command,
    CustomFieldValue,
    CustomizableResource,
    CustomSchemaPin,
    CustomValueDocument,
    DomainEvent,
    HandlerInvocationKind,
    HandlerTransaction,
    HandlingContext,
    ModuleRegistration,
    Query,
    RequestContext,
    ResourceLocator,
    ResourceOwnerFacts,
    assert_resource_owner_invocation,
)

from .models import CUSTOM_VALUES, PARTIES

PARTY_NAMESPACE = "foundation.party.party"
PARTY_CUSTOMIZABLE = CustomizableResource("1.0", PARTY_NAMESPACE, "1")


class _Input:
    model_config = ConfigDict(frozen=True, extra="forbid")


class WritePartyCustomValues(_Input, Command):
    tenant_id: UUID
    party_id: UUID
    expected_version: StrictInt = Field(ge=0, lt=2**63 - 1)
    values: tuple[CustomFieldValue, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if len({value.field_id for value in self.values}) != len(self.values):
            raise ValueError("Duplicate stable field IDs")
        return self


class ClearPartyCustomValues(_Input, Command):
    tenant_id: UUID
    party_id: UUID
    expected_version: StrictInt = Field(ge=0, lt=2**63 - 1)


class ReadPartyCustomValues(_Input, Query):
    tenant_id: UUID
    party_id: UUID
    query_operation: str = Field(default="display", max_length=30)


class ExportPartyCustomValues(ReadPartyCustomValues):
    pass


class PartyCustomValuesChanged(DomainEvent):
    event_type: ClassVar[str] = "party.custom-values.changed.v1"
    party_id: UUID
    definition_id: UUID
    revision_id: UUID
    value_version: int
    action: str


class PartyRootFacts:
    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> ResourceOwnerFacts:
        return await self._read(locator, request, transaction, locked=False)

    async def read_locked_facts(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        if action not in {"custom.write", "custom.clear"}:
            raise BusinessOSError("custom_action_unsupported", "Party custom action unsupported")
        return await self._read(locator, request, transaction, locked=True)

    async def _read(
        self,
        locator: ResourceLocator,
        request: RequestContext,
        transaction: HandlerTransaction,
        *,
        locked: bool,
    ) -> ResourceOwnerFacts:
        if (
            request.tenant is None
            or request.tenant.tenant_id != locator.tenant_id
            or locator.namespace != PARTY_NAMESPACE
            or locator.contract_version != "1"
        ):
            raise BusinessOSError(
                "forbidden", "Exact Party tenant and canonical identity required", status_code=403
            )
        statement = select(PARTIES.c.is_active).where(
            PARTIES.c.tenant_id == locator.tenant_id, PARTIES.c.id == locator.record_id
        )
        if locked:
            statement = statement.with_for_update()
        row = (await transaction.persistence.execute(statement)).one_or_none()
        if row is None:
            raise BusinessOSError("not_found", "Party not found", status_code=404)
        return ResourceOwnerFacts(
            locator.tenant_id,
            PARTY_NAMESPACE,
            locator.record_id,
            "foundation.party",
            "1",
            "active" if row.is_active else "inactive",
            {"custom_fields": True, "writes_require_active": True, "query_tier": "display"},
        )


class PartyCustomFields:
    version = "1.0"

    def register(self, registration: ModuleRegistration) -> None:
        registration.resource_owner_facts(PARTY_NAMESPACE, "1", PartyRootFacts())
        registration.contract("foundation.party.custom-values.v1", self)
        registration.contract("foundation.party.customizable-resource.v1", PARTY_CUSTOMIZABLE)
        registration.contract(
            "foundation.party.custom-query-capabilities.v1", PARTY_CUSTOMIZABLE.query
        )
        registration.command(
            WritePartyCustomValues, self.write, permission="foundation.party.manage"
        )
        registration.command(
            ClearPartyCustomValues, self.clear, permission="foundation.party.manage"
        )
        registration.query(ReadPartyCustomValues, self.read, permission="foundation.party.read")
        registration.query(ExportPartyCustomValues, self.read, permission="foundation.party.read")

    async def _admit(
        self, tenant_id: UUID, party_id: UUID, ctx: HandlingContext, *, action: str | None
    ) -> ResourceLocator:
        if ctx.request.tenant is None or ctx.request.tenant.tenant_id != tenant_id:
            raise BusinessOSError("forbidden", "Trusted Party tenant required", status_code=403)
        locator = ResourceLocator(PARTY_NAMESPACE, "1", party_id, tenant_id)
        owners = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        assert_resource_owner_invocation(
            ctx.invocation,
            locator,
            ctx.request,
            ctx.unit_of_work,
            owners,
            invocation_kind=(
                HandlerInvocationKind.QUERY if action is None else HandlerInvocationKind.COMMAND
            ),
        )
        provider = await owners.resolve_provider(locator, "facts", ctx.request, ctx.unit_of_work)
        facts = (
            await provider.read_facts()
            if action is None
            else await provider.read_locked_facts(action)
        )
        if action is not None and facts.lifecycle != "active":
            raise BusinessOSError(
                "party_inactive", "Inactive Party custom values are not writable", status_code=409
            )
        return locator

    async def read(
        self, query: ReadPartyCustomValues, ctx: HandlingContext
    ) -> CustomValueDocument | None:
        PARTY_CUSTOMIZABLE.query.require(query.query_operation)
        locator = await self._admit(query.tenant_id, query.party_id, ctx, action=None)
        row = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(CUSTOM_VALUES).where(
                        CUSTOM_VALUES.c.tenant_id == locator.tenant_id,
                        CUSTOM_VALUES.c.party_id == locator.record_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        resolver = await ctx.dependencies.resolve(PUBLISHED_CUSTOM_FIELD_SCHEMA)
        schema = await resolver.resolve(
            locator,
            ctx,
            pin=CustomSchemaPin(row["definition_id"], row["revision_id"], row["revision_digest"]),
        )
        schema.validate_values(row["value_document"], cleared=row["cleared"])
        return self._document(locator, dict(row))

    async def write(self, cmd: WritePartyCustomValues, ctx: HandlingContext) -> CustomValueDocument:
        # Snapshot nested boundary JSON before any await to prevent mid-validation mutation.
        values = {
            str(item["field_id"]): item["value"] for item in cmd.model_dump(mode="json")["values"]
        }
        return await self._mutate(
            cmd.tenant_id, cmd.party_id, cmd.expected_version, values, ctx, cleared=False
        )

    async def clear(self, cmd: ClearPartyCustomValues, ctx: HandlingContext) -> CustomValueDocument:
        return await self._mutate(
            cmd.tenant_id, cmd.party_id, cmd.expected_version, {}, ctx, cleared=True
        )

    async def _mutate(
        self,
        tenant_id: UUID,
        party_id: UUID,
        expected: int,
        values: dict[str, object],
        ctx: HandlingContext,
        *,
        cleared: bool,
    ) -> CustomValueDocument:
        locator = await self._admit(
            tenant_id, party_id, ctx, action="custom.clear" if cleared else "custom.write"
        )
        row = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(CUSTOM_VALUES)
                    .where(
                        CUSTOM_VALUES.c.tenant_id == tenant_id, CUSTOM_VALUES.c.party_id == party_id
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if (row["value_version"] if row is not None else 0) != expected:
            raise BusinessOSError(
                "custom_value_conflict", "Custom value version conflict", status_code=409
            )
        resolver = await ctx.dependencies.resolve(PUBLISHED_CUSTOM_FIELD_SCHEMA)
        # Clear retained values using their pin; a first clear uses the active schema.
        pin = (
            CustomSchemaPin(row["definition_id"], row["revision_id"], row["revision_digest"])
            if cleared and row is not None
            else None
        )
        schema = await resolver.resolve(locator, ctx, pin=pin)
        validated = json.loads(schema.validate_values(values, cleared=cleared))
        tenant = ctx.request.tenant
        assert tenant is not None
        data = {
            "tenant_id": tenant_id,
            "party_id": party_id,
            "definition_id": schema.pin.definition_id,
            "revision_id": schema.pin.revision_id,
            "revision_digest": schema.pin.digest,
            "value_version": expected + 1,
            "value_document": validated,
            "cleared": cleared,
            "updated_by": tenant.principal_id,
        }
        statement: Insert | Update
        if row is None:
            statement = insert(CUSTOM_VALUES).values(**data)
        else:
            from sqlalchemy import func

            statement = (
                update(CUSTOM_VALUES)
                .where(CUSTOM_VALUES.c.tenant_id == tenant_id, CUSTOM_VALUES.c.party_id == party_id)
                .values(**data, updated_at=func.now())
            )
        await ctx.unit_of_work.persistence.execute(statement)
        ctx.emit(
            PartyCustomValuesChanged(
                tenant_id=tenant_id,
                correlation_id=ctx.request.correlation_id,
                party_id=party_id,
                definition_id=schema.pin.definition_id,
                revision_id=schema.pin.revision_id,
                value_version=expected + 1,
                action="clear" if cleared else "replace",
            )
        )
        return self._document(locator, data)

    @staticmethod
    def _document(locator: ResourceLocator, row: Mapping[str, object]) -> CustomValueDocument:
        values = row["value_document"]
        assert isinstance(values, dict)
        value_map = cast(dict[str, JsonValue], values)
        return CustomValueDocument.model_validate(
            {
                "tenant_id": locator.tenant_id,
                "resource_namespace": locator.namespace,
                "record_id": locator.record_id,
                "definition_id": row["definition_id"],
                "revision_id": row["revision_id"],
                "revision_digest": row["revision_digest"],
                "value_version": row["value_version"],
                "cleared": row["cleared"],
                "values": [
                    {"field_id": key, "value": value} for key, value in sorted(value_map.items())
                ],
            }
        )
