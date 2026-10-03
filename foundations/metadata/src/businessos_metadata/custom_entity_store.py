"""Private Metadata-owned instance persistence in the protected dispatcher UOW."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, insert, select, text, update

from businessos.sdk import (
    AUTHORIZER,
    RESOURCE_OWNER_RESOLVER,
    BusinessOSError,
    CustomFieldValue,
    CustomSchemaPin,
    HandlerInvocationKind,
    HandlingContext,
    ResourceLocator,
    assert_resource_owner_invocation,
)

from .contracts import (
    CanonicalResourceReference,
    DefinitionKind,
    DefinitionSnapshot,
    FieldType,
    MetadataLimits,
    ReferenceResolution,
    ReferenceState,
)
from .custom_entities import (
    CUSTOM_ENTITY_NAMESPACE,
    CustomEntityExport,
    CustomEntityIdentity,
    CustomEntityLimits,
    CustomEntityPage,
    CustomEntityRecord,
    CustomEntityScopeKind,
)
from .custom_schema import (
    _PublishedSchema,  # pyright: ignore[reportPrivateUsage] -- same-owner certified grammar reuse
)
from .models import CUSTOM_ENTITIES, DEFINITIONS, REVISIONS
from .store import _tenant  # pyright: ignore[reportPrivateUsage] -- same-owner context validation

if TYPE_CHECKING:
    from .module import (
        ArchiveCustomEntity,
        CreateCustomEntity,
        ListCustomEntities,
        UpdateCustomEntity,
    )


class CustomEntityStore:
    """Stored state contains limits only, never a privileged callback/pool/UOW."""

    def __init__(self, metadata_limits: MetadataLimits, limits: CustomEntityLimits) -> None:
        self._metadata_limits = metadata_limits
        self._limits = limits

    async def _admit(self, identity: UUID, ctx: HandlingContext, *, writing: bool) -> UUID:
        tenant_id, _ = _tenant(ctx)
        owners = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        assert_resource_owner_invocation(
            ctx.invocation,
            ResourceLocator(CUSTOM_ENTITY_NAMESPACE, "1", identity, tenant_id),
            ctx.request,
            ctx.unit_of_work,
            owners,
            invocation_kind=HandlerInvocationKind.COMMAND
            if writing
            else HandlerInvocationKind.QUERY,
        )
        authorizer = await ctx.dependencies.resolve(AUTHORIZER)
        await authorizer.require(ctx.request, "foundation.metadata.definition.read")
        return tenant_id

    async def _serialize(self, ctx: HandlingContext) -> None:
        tenant_id, _ = _tenant(ctx)
        await ctx.unit_of_work.persistence.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"metadata-custom-entity:{tenant_id}"},
        )

    def _scope(self, row: Mapping[str, Any], ctx: HandlingContext) -> None:
        tenant = ctx.request.tenant
        if tenant is None or row["tenant_id"] != tenant.tenant_id:
            raise BusinessOSError("not_found", "Custom entity unavailable", status_code=404)
        kind = CustomEntityScopeKind(row["scope_kind"])
        if kind.trusted_id(tenant) != row["scope_id"]:
            raise BusinessOSError("not_found", "Custom entity unavailable", status_code=404)

    async def _definition(self, definition_id: UUID, ctx: HandlingContext) -> Mapping[str, Any]:
        tenant_id, _ = _tenant(ctx)
        row = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(DEFINITIONS).where(
                        DEFINITIONS.c.tenant_id == tenant_id,
                        DEFINITIONS.c.id == definition_id,
                        DEFINITIONS.c.kind == DefinitionKind.CUSTOM_ENTITY.value,
                        DEFINITIONS.c.resource_namespace == CUSTOM_ENTITY_NAMESPACE,
                        DEFINITIONS.c.owner_module_id == "foundation.metadata",
                        DEFINITIONS.c.owner_contract_version == "1",
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BusinessOSError("not_found", "Custom entity type unavailable", status_code=404)
        return cast(Mapping[str, Any], row)

    def _schema(self, snapshot: object, digest: str) -> DefinitionSnapshot:
        schema = DefinitionSnapshot.model_validate(snapshot)
        if schema.kind is not DefinitionKind.CUSTOM_ENTITY or schema.digest() != digest:
            raise BusinessOSError("custom_schema_invalid", "Immutable custom entity pin invalid")
        schema.validate_limits(self._metadata_limits)
        if any(f.classification_ref is not None for f in schema.fields):
            raise BusinessOSError(
                "classification_unavailable", "Authoritative classification unavailable"
            )
        if any(
            f.value_type is FieldType.REFERENCE
            and (
                f.reference_namespace != CUSTOM_ENTITY_NAMESPACE
                or f.reference_contract_version != "1"
            )
            for f in schema.fields
        ):
            raise BusinessOSError(
                "custom_reference_unsupported", "Cross-owner reference unsupported"
            )
        return schema

    async def _revision(
        self, definition_id: UUID, revision_id: UUID, ctx: HandlingContext
    ) -> Mapping[str, Any]:
        tenant_id, _ = _tenant(ctx)
        row = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(REVISIONS).where(
                        REVISIONS.c.tenant_id == tenant_id,
                        REVISIONS.c.definition_id == definition_id,
                        REVISIONS.c.id == revision_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BusinessOSError(
                "custom_schema_invalid", "Immutable custom entity revision unavailable"
            )
        self._schema(row["snapshot"], row["digest"])
        return cast(Mapping[str, Any], row)

    async def _active(self, definition_id: UUID, ctx: HandlingContext) -> Mapping[str, Any]:
        definition = await self._definition(definition_id, ctx)
        if definition["lifecycle"] != "published" or definition["active_revision_id"] is None:
            raise BusinessOSError(
                "custom_type_inactive", "Published custom entity type required", status_code=409
            )
        # No definition lock or second transaction: publication can advance while
        # this exact immutable revision remains the validated write pin.
        return await self._revision(definition_id, definition["active_revision_id"], ctx)

    def _values(
        self, schema: DefinitionSnapshot, values: Mapping[str, object], tenant_id: UUID
    ) -> tuple[str, tuple[CanonicalResourceReference, ...]]:
        schema.validate_limits(self._metadata_limits)
        fields = {str(f.field_id): f for f in schema.fields}
        canonical_values = dict(values)
        if set(values) - fields.keys():
            raise BusinessOSError("custom_values_invalid", "Unknown stable field ID")
        references: list[CanonicalResourceReference] = []
        for key, field in fields.items():
            if field.value_type is not FieldType.REFERENCE:
                continue
            value = values.get(key)
            if value is None:
                if not field.nullable:
                    raise BusinessOSError("custom_values_invalid", "Required reference missing")
                continue
            try:
                reference = CanonicalResourceReference.model_validate(value)
            except ValueError:
                raise BusinessOSError(
                    "custom_reference_invalid", "Typed reference required"
                ) from None
            if (
                reference.tenant_id != tenant_id
                or reference.resource_namespace != CUSTOM_ENTITY_NAMESPACE
                or reference.contract_version != "1"
            ):
                raise BusinessOSError(
                    "custom_reference_invalid", "Exact same-tenant Metadata reference required"
                )
            references.append(reference)
            canonical_values[key] = reference.model_dump(mode="json")
        if len(references) > self._limits.max_references:
            raise BusinessOSError("quota_exceeded", "Reference count quota exceeded")
        # Reuse the certified literal/rule implementation. A reference's technical
        # UUID is the bounded literal projection after its complete typed identity
        # was validated above. This also preserves conditional-required rules whose
        # required field is a reference. Target authorization/lifecycle follows in
        # the same protected UOW. No stored schema or digest is changed.
        literal_schema = schema.model_copy(
            update={
                "fields": tuple(
                    f.model_copy(
                        update={
                            "value_type": FieldType.UUID,
                            "reference_namespace": None,
                            "reference_contract_version": None,
                        }
                    )
                    if f.value_type is FieldType.REFERENCE
                    else f
                    for f in schema.fields
                )
            }
        )
        literal_values = dict(values)
        for key, field in fields.items():
            if field.value_type is FieldType.REFERENCE and values.get(key) is not None:
                literal_values[key] = str(
                    CanonicalResourceReference.model_validate(values[key]).record_id
                )
        _PublishedSchema(
            CustomSchemaPin(UUID(int=0), UUID(int=0), schema.digest()),
            literal_schema,
            self._metadata_limits,
        ).validate_values(literal_values)
        try:
            document = json.dumps(
                canonical_values,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (ValueError, TypeError):
            raise BusinessOSError("custom_values_invalid", "Invalid canonical document") from None
        if len(document.encode()) > self._metadata_limits.max_document_bytes:
            raise BusinessOSError("quota_exceeded", "Value document byte quota exceeded")
        return document, tuple(references)

    async def _references(
        self,
        references: tuple[CanonicalResourceReference, ...],
        ctx: HandlingContext,
        *,
        writing: bool,
    ) -> tuple[ReferenceResolution, ...]:
        if not references:
            return ()
        authorizer = await ctx.dependencies.resolve(AUTHORIZER)
        try:
            await authorizer.require(ctx.request, "foundation.metadata.custom_entity.read")
        except BusinessOSError:
            if writing:
                raise
            return tuple(
                ReferenceResolution(
                    reference=r, state=ReferenceState.UNAVAILABLE, referenceable=False
                )
                for r in references
            )
        tenant_id, _ = _tenant(ctx)
        ids = sorted({r.record_id for r in references})
        statement = (
            select(
                CUSTOM_ENTITIES.c.id,
                CUSTOM_ENTITIES.c.tenant_id,
                CUSTOM_ENTITIES.c.scope_kind,
                CUSTOM_ENTITIES.c.scope_id,
                CUSTOM_ENTITIES.c.lifecycle,
                DEFINITIONS.c.lifecycle.label("type_lifecycle"),
                REVISIONS.c.snapshot,
                REVISIONS.c.digest,
            )
            .select_from(
                CUSTOM_ENTITIES.join(
                    DEFINITIONS,
                    and_(
                        CUSTOM_ENTITIES.c.tenant_id == DEFINITIONS.c.tenant_id,
                        CUSTOM_ENTITIES.c.definition_id == DEFINITIONS.c.id,
                    ),
                ).join(
                    REVISIONS,
                    and_(
                        CUSTOM_ENTITIES.c.tenant_id == REVISIONS.c.tenant_id,
                        CUSTOM_ENTITIES.c.definition_id == REVISIONS.c.definition_id,
                        CUSTOM_ENTITIES.c.revision_id == REVISIONS.c.id,
                        CUSTOM_ENTITIES.c.revision_digest == REVISIONS.c.digest,
                    ),
                )
            )
            .where(CUSTOM_ENTITIES.c.tenant_id == tenant_id, CUSTOM_ENTITIES.c.id.in_(ids))
        )
        rows = {
            r["id"]: r for r in (await ctx.unit_of_work.persistence.execute(statement)).mappings()
        }
        results: list[ReferenceResolution] = []
        for reference in references:
            row = rows.get(reference.record_id)
            state = ReferenceState.UNAVAILABLE
            if row is not None:
                try:
                    self._scope(dict(row), ctx)
                    self._schema(row["snapshot"], row["digest"])
                except BusinessOSError:
                    pass
                else:
                    state = (
                        ReferenceState.AVAILABLE
                        if row["lifecycle"] == "current" and row["type_lifecycle"] == "published"
                        else ReferenceState.RETIRED
                    )
            if writing and state is not ReferenceState.AVAILABLE:
                raise BusinessOSError(
                    "custom_reference_unavailable", "Reference target unavailable", status_code=409
                )
            results.append(
                ReferenceResolution(
                    reference=reference,
                    state=state,
                    referenceable=state is ReferenceState.AVAILABLE,
                )
            )
        return tuple(results)

    async def _row(
        self, instance_id: UUID, ctx: HandlingContext, *, locked: bool = False
    ) -> Mapping[str, Any]:
        tenant_id, _ = _tenant(ctx)
        statement = select(CUSTOM_ENTITIES).where(
            CUSTOM_ENTITIES.c.tenant_id == tenant_id, CUSTOM_ENTITIES.c.id == instance_id
        )
        if locked:
            statement = statement.with_for_update()
        row = (await ctx.unit_of_work.persistence.execute(statement)).mappings().one_or_none()
        if row is None:
            raise BusinessOSError("not_found", "Custom entity unavailable", status_code=404)
        self._scope(dict(row), ctx)
        return cast(Mapping[str, Any], row)

    async def _record(self, row: Mapping[str, Any], ctx: HandlingContext) -> CustomEntityRecord:
        await self._definition(row["definition_id"], ctx)
        revision = await self._revision(row["definition_id"], row["revision_id"], ctx)
        if revision["digest"] != row["revision_digest"]:
            raise BusinessOSError("custom_schema_invalid", "Immutable digest mismatch")
        _, references = self._values(
            self._schema(revision["snapshot"], revision["digest"]),
            row["value_document"],
            row["tenant_id"],
        )
        return CustomEntityRecord(
            identity=CustomEntityIdentity(
                tenant_id=row["tenant_id"],
                entity_type_id=row["definition_id"],
                instance_id=row["id"],
            ),
            revision_id=row["revision_id"],
            revision_digest=row["revision_digest"],
            lifecycle=row["lifecycle"],
            scope_kind=row["scope_kind"],
            scope_id=row["scope_id"],
            value_version=row["value_version"],
            values=tuple(
                CustomFieldValue(field_id=UUID(k), value=v)
                for k, v in sorted(row["value_document"].items())
            ),
            created_by=row["created_by"],
            updated_by=row["updated_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
            references=await self._references(references, ctx, writing=False),
        )

    async def create(self, cmd: CreateCustomEntity, ctx: HandlingContext) -> CustomEntityRecord:
        values = {str(v["field_id"]): v["value"] for v in cmd.model_dump(mode="json")["values"]}
        tenant_id = await self._admit(cmd.entity_type_id, ctx, writing=True)
        tenant = ctx.request.tenant
        assert tenant is not None
        scope_id = cmd.scope_kind.trusted_id(tenant)
        await self._serialize(ctx)
        revision = await self._active(cmd.entity_type_id, ctx)
        document, references = self._values(
            self._schema(revision["snapshot"], revision["digest"]), values, tenant_id
        )
        await self._references(references, ctx, writing=True)
        counts = (
            await ctx.unit_of_work.persistence.execute(
                select(
                    func.count().label("tenant_count"),
                    func.count()
                    .filter(CUSTOM_ENTITIES.c.definition_id == cmd.entity_type_id)
                    .label("type_count"),
                )
                .select_from(CUSTOM_ENTITIES)
                .where(CUSTOM_ENTITIES.c.tenant_id == tenant_id)
            )
        ).one()
        if (
            counts.tenant_count >= self._limits.max_instances_per_tenant
            or counts.type_count >= self._limits.max_instances_per_type
        ):
            raise BusinessOSError(
                "quota_exceeded", "Custom entity storage quota exceeded", status_code=409
            )
        identity = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(CUSTOM_ENTITIES).values(
                id=identity,
                tenant_id=tenant_id,
                definition_id=cmd.entity_type_id,
                revision_id=revision["id"],
                revision_digest=revision["digest"],
                lifecycle="current",
                scope_kind=cmd.scope_kind.value,
                scope_id=scope_id,
                value_version=1,
                value_document=json.loads(document),
                created_by=tenant.principal_id,
                updated_by=tenant.principal_id,
            )
        )
        return await self._record(await self._row(identity, ctx), ctx)

    async def read(self, instance_id: UUID, ctx: HandlingContext) -> CustomEntityRecord:
        await self._admit(instance_id, ctx, writing=False)
        return await self._record(await self._row(instance_id, ctx), ctx)

    async def export(self, instance_id: UUID, ctx: HandlingContext) -> CustomEntityExport:
        return CustomEntityExport(record=await self.read(instance_id, ctx))

    async def mutate(
        self, cmd: UpdateCustomEntity | ArchiveCustomEntity, ctx: HandlingContext, *, archive: bool
    ) -> CustomEntityRecord:
        payload = cmd.model_dump(mode="json")
        values = {str(v["field_id"]): v["value"] for v in payload.get("values", [])}
        await self._admit(cmd.instance_id, ctx, writing=True)
        await self._serialize(ctx)
        row = await self._row(cmd.instance_id, ctx, locked=True)
        if row["lifecycle"] != "current":
            raise BusinessOSError(
                "custom_entity_archived", "Archived instance is immutable", status_code=409
            )
        if row["value_version"] != cmd.expected_version or row["value_version"] >= 2**63 - 1:
            raise BusinessOSError(
                "custom_entity_conflict", "Instance version changed", status_code=409
            )
        # A writable active schema must not launder an unavailable retained pin
        # (including classification) into an unclassified replacement.
        await self._record(row, ctx)
        if archive:
            changes: dict[str, Any] = {"lifecycle": "archived", "archived_at": func.now()}
        else:
            revision = await self._active(row["definition_id"], ctx)
            document, references = self._values(
                self._schema(revision["snapshot"], revision["digest"]), values, row["tenant_id"]
            )
            await self._references(references, ctx, writing=True)
            changes = {
                "value_document": json.loads(document),
                "revision_id": revision["id"],
                "revision_digest": revision["digest"],
            }
        _, principal_id = _tenant(ctx)
        changes.update(
            value_version=row["value_version"] + 1, updated_by=principal_id, updated_at=func.now()
        )
        await ctx.unit_of_work.persistence.execute(
            update(CUSTOM_ENTITIES)
            .where(
                CUSTOM_ENTITIES.c.tenant_id == row["tenant_id"],
                CUSTOM_ENTITIES.c.id == row["id"],
                CUSTOM_ENTITIES.c.value_version == cmd.expected_version,
            )
            .values(**changes)
        )
        return await self._record(await self._row(row["id"], ctx), ctx)

    async def list(self, query: ListCustomEntities, ctx: HandlingContext) -> CustomEntityPage:
        tenant_id = await self._admit(query.entity_type_id, ctx, writing=False)
        await self._definition(query.entity_type_id, ctx)
        tenant = ctx.request.tenant
        assert tenant is not None
        if query.page_size > self._limits.max_page_size:
            raise BusinessOSError("quota_exceeded", "Page size exceeds configured quota")
        statement = select(CUSTOM_ENTITIES).where(
            CUSTOM_ENTITIES.c.tenant_id == tenant_id,
            CUSTOM_ENTITIES.c.definition_id == query.entity_type_id,
            CUSTOM_ENTITIES.c.scope_kind == query.scope_kind.value,
            CUSTOM_ENTITIES.c.scope_id == query.scope_kind.trusted_id(tenant),
        )
        if query.after is not None:
            statement = statement.where(CUSTOM_ENTITIES.c.id > query.after)
        rows = (
            (
                await ctx.unit_of_work.persistence.execute(
                    statement.order_by(CUSTOM_ENTITIES.c.id).limit(query.page_size + 1)
                )
            )
            .mappings()
            .all()
        )
        records = tuple([await self._record(dict(row), ctx) for row in rows[: query.page_size]])
        return CustomEntityPage(
            records=records,
            next_after=records[-1].identity.instance_id if len(rows) > query.page_size else None,
        )
