"""Metadata-owned definition repository and one-UOW publication lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text, update

from businessos.sdk import RESOURCE_OWNER_RESOLVER, BusinessOSError, HandlingContext

from .contracts import (
    DefinitionIdentity,
    DefinitionLifecycle,
    DefinitionRecord,
    DefinitionSnapshot,
    DraftRecord,
    GenerationExpectation,
    MetadataLimits,
    PublicationResult,
    PublicationStatus,
    PublishPreflight,
    RevisionRecord,
)
from .custom_entities import CUSTOM_ENTITY_NAMESPACE
from .custom_entity_definitions import (
    CustomEntityDefinitionIdentity,
    CustomEntityDefinitionRecord,
    CustomEntityDefinitionSnapshot,
    CustomEntityDraftRecord,
    CustomEntityRevisionRecord,
    internal_snapshot,
)
from .models import CONTRACT_FENCE, DEFINITIONS, MODULE_FENCE, REVISION_MODULE_BINDINGS, REVISIONS

if TYPE_CHECKING:
    from .module import (
        CreateCustomEntityDefinition,
        CreateDefinition,
        EditCustomEntityDraft,
        EditDraft,
        RetireCustomEntityDefinition,
        RetireDefinition,
    )


def _tenant(ctx: HandlingContext) -> tuple[UUID, UUID]:
    trusted = ctx.request.tenant
    if (
        trusted is None
        or type(trusted.tenant_id) is not UUID
        or type(trusted.principal_id) is not UUID
    ):
        raise BusinessOSError(
            "tenant_required", "Trusted tenant and principal required", status_code=403
        )
    return trusted.tenant_id, trusted.principal_id


def _definition(row: Mapping[str, Any]) -> DefinitionRecord | CustomEntityDefinitionRecord:
    identity = dict(
        definition_id=row["id"],
        tenant_id=row["tenant_id"],
        owner_module_id=row["owner_module_id"],
        resource_namespace=row["resource_namespace"],
        owner_contract_version=row["owner_contract_version"],
        kind=row["kind"],
    )
    facts = dict(
        lifecycle=row["lifecycle"],
        draft_generation=row["draft_generation"],
        active_revision_id=row["active_revision_id"],
        active_generation=row["active_generation"],
    )
    if row["kind"] == "custom_entity":
        return CustomEntityDefinitionRecord(
            identity=CustomEntityDefinitionIdentity(**identity), **facts
        )
    return DefinitionRecord(identity=DefinitionIdentity(**identity), **facts)


def _revision(row: Mapping[str, Any]) -> RevisionRecord | CustomEntityRevisionRecord:
    facts = dict(
        revision_id=row["id"],
        tenant_id=row["tenant_id"],
        definition_id=row["definition_id"],
        sequence=row["sequence"],
        digest=row["digest"],
        published_at=row["published_at"],
        provenance=row["provenance"],
    )
    if row["snapshot"]["kind"] == "custom_entity":
        return CustomEntityRevisionRecord(
            snapshot=CustomEntityDefinitionSnapshot.model_validate(row["snapshot"]), **facts
        )
    return RevisionRecord(snapshot=DefinitionSnapshot.model_validate(row["snapshot"]), **facts)


def _draft(row: Mapping[str, Any]) -> DraftRecord | CustomEntityDraftRecord:
    definition = _definition(row)
    if isinstance(definition, CustomEntityDefinitionRecord):
        return CustomEntityDraftRecord(
            definition=definition,
            snapshot=CustomEntityDefinitionSnapshot.model_validate(row["draft_snapshot"]),
        )
    return DraftRecord(
        definition=definition, snapshot=DefinitionSnapshot.model_validate(row["draft_snapshot"])
    )


def _failure(
    preflight: PublishPreflight, status: PublicationStatus, diagnostic: str
) -> PublicationResult:
    return PublicationResult(
        status=status,
        definition_id=preflight.definition_id,
        diagnostic=diagnostic,
    )


class MetadataStore:
    """All writes use the dispatcher's tenant-bound UOW and its rollback boundary."""

    def __init__(self, limits: MetadataLimits) -> None:
        self._limits = limits

    async def _row(
        self, definition_id: UUID, ctx: HandlingContext, *, locked: bool = False
    ) -> Mapping[str, Any] | None:
        tenant_id, _ = _tenant(ctx)
        statement = select(DEFINITIONS).where(
            DEFINITIONS.c.id == definition_id, DEFINITIONS.c.tenant_id == tenant_id
        )
        if locked:
            statement = statement.with_for_update()
        result = await ctx.unit_of_work.persistence.execute(statement)
        found = result.mappings().one_or_none()
        return cast(Mapping[str, Any] | None, found)

    async def _revision_row(
        self, revision_id: UUID, definition_id: UUID, ctx: HandlingContext
    ) -> Mapping[str, Any] | None:
        tenant_id, _ = _tenant(ctx)
        result = await ctx.unit_of_work.persistence.execute(
            select(REVISIONS).where(
                REVISIONS.c.id == revision_id,
                REVISIONS.c.tenant_id == tenant_id,
                REVISIONS.c.definition_id == definition_id,
            )
        )
        return cast(Mapping[str, Any] | None, result.mappings().one_or_none())

    async def _owner_and_dependencies(
        self,
        row: Mapping[str, Any],
        snapshot: DefinitionSnapshot | CustomEntityDefinitionSnapshot,
        ctx: HandlingContext,
    ) -> tuple[str, ...]:
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        owner = resolver.resolve_owner(row["resource_namespace"], row["owner_contract_version"])
        if (
            owner.ownership.owner_module_id != row["owner_module_id"]
            or owner.ownership.resource_namespace != row["resource_namespace"]
        ):
            raise BusinessOSError("owner_unavailable", "Canonical owner changed", status_code=409)
        modules = {row["owner_module_id"]}
        for field in snapshot.fields:
            if field.reference_namespace is None:
                continue
            target = resolver.resolve_owner(
                field.reference_namespace, field.reference_contract_version or ""
            )
            if target.ownership.resource_namespace != field.reference_namespace:
                raise BusinessOSError(
                    "reference_owner_unavailable",
                    "Reference owner is not canonical",
                    status_code=409,
                )
            modules.add(target.ownership.owner_module_id)
        return tuple(sorted(modules))

    def _validate_snapshot(
        self,
        snapshot: DefinitionSnapshot | CustomEntityDefinitionSnapshot,
        *,
        publishing: bool = False,
    ) -> None:
        internal_snapshot(snapshot.model_dump(mode="json"))
        snapshot.validate_limits(self._limits)
        # ADR-015's authoritative classification resolver is a separate
        # certification prerequisite. A classified field cannot publish by
        # treating a missing resolver as an unclassified fallback.
        if publishing and any(field.classification_ref is not None for field in snapshot.fields):
            raise BusinessOSError(
                "classification_unavailable",
                "Classified custom fields await the authoritative resolver",
                status_code=409,
            )

    async def create(
        self, cmd: CreateDefinition | CreateCustomEntityDefinition, ctx: HandlingContext
    ) -> DefinitionRecord | CustomEntityDefinitionRecord:
        tenant_id, principal_id = _tenant(ctx)
        from .module import CreateCustomEntityDefinition

        if (cmd.kind.value == "custom_entity") != isinstance(cmd, CreateCustomEntityDefinition):
            raise BusinessOSError(
                "definition_contract_required",
                "Use the matching versioned definition contract",
                status_code=409,
            )
        self._validate_snapshot(cmd.snapshot)
        if cmd.snapshot.kind.value != cmd.kind.value:
            raise BusinessOSError("kind_mismatch", "Definition kind mismatch", status_code=400)
        if (cmd.kind.value == "custom_entity") != (
            cmd.resource_namespace == CUSTOM_ENTITY_NAMESPACE
        ) or (cmd.kind.value == "custom_entity" and cmd.owner_contract_version != "1"):
            raise BusinessOSError(
                "kind_mismatch", "Custom entity kind requires exact Metadata family"
            )
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        owner = resolver.resolve_owner(cmd.resource_namespace, cmd.owner_contract_version)
        if owner.ownership.resource_namespace != cmd.resource_namespace:
            raise BusinessOSError("owner_mismatch", "Canonical resource required", status_code=409)
        # Serialize quota checks within a tenant without a mutable global
        # counter or application-only check under concurrent creators.
        await ctx.unit_of_work.persistence.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"metadata-definition-count:{tenant_id}"},
        )
        count = (
            await ctx.unit_of_work.persistence.execute(
                select(func.count())
                .select_from(DEFINITIONS)
                .where(DEFINITIONS.c.tenant_id == tenant_id)
            )
        ).scalar_one()
        if count >= self._limits.max_definitions_per_tenant:
            raise BusinessOSError(
                "quota_exceeded", "Metadata definition quota exceeded", status_code=409
            )
        definition_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(DEFINITIONS).values(
                id=definition_id,
                tenant_id=tenant_id,
                owner_module_id=owner.ownership.owner_module_id,
                resource_namespace=cmd.resource_namespace,
                owner_contract_version=cmd.owner_contract_version,
                kind=cmd.kind.value,
                lifecycle=DefinitionLifecycle.DRAFT.value,
                draft_generation=1,
                draft_snapshot=cmd.snapshot.model_dump(mode="json"),
                active_revision_id=None,
                active_generation=0,
                created_by=principal_id,
            )
        )
        row = await self._row(definition_id, ctx)
        assert row is not None
        return _definition(row)

    async def edit(
        self, cmd: EditDraft | EditCustomEntityDraft, ctx: HandlingContext
    ) -> DraftRecord | CustomEntityDraftRecord:
        row = await self._row(cmd.definition_id, ctx, locked=True)
        if row is None:
            raise BusinessOSError("not_found", "Metadata definition not found", status_code=404)
        from .module import EditCustomEntityDraft

        self._surface(row, isinstance(cmd, EditCustomEntityDraft))
        if row["lifecycle"] == DefinitionLifecycle.RETIRED.value:
            raise BusinessOSError("retired", "Retired definition cannot be edited", status_code=409)
        if row["draft_generation"] != cmd.expected_draft_generation:
            raise BusinessOSError("stale_draft", "Draft generation changed", status_code=409)
        if row["kind"] != cmd.snapshot.kind.value:
            raise BusinessOSError("kind_mismatch", "Definition kind cannot change", status_code=409)
        self._validate_snapshot(cmd.snapshot)
        await self._owner_and_dependencies(row, cmd.snapshot, ctx)
        await ctx.unit_of_work.persistence.execute(
            update(DEFINITIONS)
            .where(DEFINITIONS.c.id == cmd.definition_id)
            .values(
                draft_snapshot=cmd.snapshot.model_dump(mode="json"),
                draft_generation=row["draft_generation"] + 1,
                updated_at=func.now(),
            )
        )
        updated = await self._row(cmd.definition_id, ctx)
        assert updated is not None
        return _draft(updated)

    async def read_draft(
        self, definition_id: UUID, ctx: HandlingContext, *, custom: bool = False
    ) -> DraftRecord | CustomEntityDraftRecord | None:
        row = await self._row(definition_id, ctx)
        if row is None or row["lifecycle"] == DefinitionLifecycle.RETIRED.value:
            return None
        self._surface(row, custom)
        return _draft(row)

    async def read_active(
        self,
        definition_id: UUID,
        ctx: HandlingContext,
        *,
        custom: bool = False,
        internal: bool = False,
    ) -> RevisionRecord | CustomEntityRevisionRecord | None:
        row = await self._row(definition_id, ctx)
        if row is None or row["lifecycle"] != DefinitionLifecycle.PUBLISHED.value:
            return None
        if not internal:
            self._surface(row, custom)
        revision_id = row["active_revision_id"]
        if revision_id is None:
            return None
        revision = await self._revision_row(revision_id, definition_id, ctx)
        if revision is None:
            raise BusinessOSError(
                "active_revision_missing", "Active revision unavailable", status_code=409
            )
        snapshot = internal_snapshot(revision["snapshot"])
        await self._owner_and_dependencies(row, snapshot, ctx)
        return _revision(revision)

    @staticmethod
    def _surface(row: Mapping[str, Any], custom: bool) -> None:
        if (row["kind"] == "custom_entity") != custom:
            raise BusinessOSError(
                "definition_contract_required",
                "Use the matching versioned definition contract",
                status_code=409,
            )

    async def _bindings(
        self, revision_id: UUID | None, ctx: HandlingContext
    ) -> tuple[GenerationExpectation, ...]:
        if revision_id is None:
            return ()
        tenant_id, _ = _tenant(ctx)
        result = await ctx.unit_of_work.persistence.execute(
            select(REVISION_MODULE_BINDINGS).where(
                REVISION_MODULE_BINDINGS.c.tenant_id == tenant_id,
                REVISION_MODULE_BINDINGS.c.revision_id == revision_id,
            )
        )
        return tuple(
            GenerationExpectation(
                module_id=item["module_id"],
                artifact_identity=item["artifact_identity"],
                generation=item["generation"],
            )
            for item in result.mappings()
        )

    async def preflight(
        self, definition_id: UUID, target_revision_id: UUID | None, ctx: HandlingContext
    ) -> PublishPreflight:
        row = await self._row(definition_id, ctx)
        if row is None or row["lifecycle"] == DefinitionLifecycle.RETIRED.value:
            raise BusinessOSError("not_found", "Active draft unavailable", status_code=404)
        revision = (
            await self._revision_row(target_revision_id, definition_id, ctx)
            if target_revision_id is not None
            else None
        )
        if target_revision_id is not None and revision is None:
            raise BusinessOSError("not_found", "Historical revision unavailable", status_code=404)
        snapshot = internal_snapshot(
            revision["snapshot"] if revision is not None else row["draft_snapshot"]
        )
        self._validate_snapshot(snapshot, publishing=True)
        modules = await self._owner_and_dependencies(row, snapshot, ctx)
        result = await ctx.unit_of_work.persistence.execute(
            select(MODULE_FENCE).where(MODULE_FENCE.c.module_id.in_(modules))
        )
        fences = {item["module_id"]: item for item in result.mappings()}
        if len(fences) != len(modules):
            raise BusinessOSError(
                "base_unavailable", "Active module fence unavailable", status_code=409
            )
        base_id = row["owner_module_id"]
        expectations = {
            module_id: GenerationExpectation(
                module_id=module_id,
                artifact_identity=fences[module_id]["artifact_identity"],
                generation=fences[module_id]["generation"],
            )
            for module_id in modules
        }
        contract = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(CONTRACT_FENCE).where(CONTRACT_FENCE.c.id == 1)
                )
            )
            .mappings()
            .one()
        )
        return PublishPreflight(
            definition_id=definition_id,
            target_revision_id=target_revision_id,
            expected_draft_generation=row["draft_generation"],
            expected_active_revision_id=row["active_revision_id"],
            expected_active_generation=row["active_generation"],
            expected_base=expectations[base_id],
            expected_schema_generation=contract["schema_generation"],
            expected_ui_generation=contract["ui_generation"],
            dependencies=tuple(
                expectations[module_id] for module_id in modules if module_id != base_id
            ),
        )

    async def _locked_preflight(
        self, preflight: PublishPreflight, ctx: HandlingContext
    ) -> tuple[Mapping[str, Any] | None, PublicationResult | None]:
        initial = await self._row(preflight.definition_id, ctx)
        if initial is None:
            return None, _failure(
                preflight, PublicationStatus.ACTIVE_REVISION_CONFLICT, "definition missing"
            )
        old_bindings = await self._bindings(initial["active_revision_id"], ctx)
        modules = sorted(
            {
                item.module_id
                for item in (*old_bindings, preflight.expected_base, *preflight.dependencies)
            }
        )
        contract = (
            (
                await ctx.unit_of_work.persistence.execute(
                    select(CONTRACT_FENCE)
                    .where(CONTRACT_FENCE.c.id == 1)
                    .with_for_update(read=True)
                )
            )
            .mappings()
            .one()
        )
        if (
            contract["schema_generation"] != preflight.expected_schema_generation
            or contract["ui_generation"] != preflight.expected_ui_generation
        ):
            return None, _failure(
                preflight, PublicationStatus.MODULE_BASE_CHANGED, "schema/UI generation changed"
            )
        result = await ctx.unit_of_work.persistence.execute(
            select(MODULE_FENCE)
            .where(MODULE_FENCE.c.module_id.in_(modules))
            .order_by(MODULE_FENCE.c.module_id)
            .with_for_update()
        )
        current = {item["module_id"]: item for item in result.mappings()}
        for expected in (preflight.expected_base, *preflight.dependencies):
            actual = current.get(expected.module_id)
            if (
                actual is None
                or actual["artifact_identity"] != expected.artifact_identity
                or actual["generation"] != expected.generation
            ):
                code = (
                    PublicationStatus.MODULE_BASE_CHANGED
                    if expected.module_id == preflight.expected_base.module_id
                    else PublicationStatus.INCOMPATIBLE_DEPENDENCY
                )
                return None, _failure(
                    preflight, code, f"module generation changed: {expected.module_id}"
                )
        row = await self._row(preflight.definition_id, ctx, locked=True)
        if row is None or row["lifecycle"] == DefinitionLifecycle.RETIRED.value:
            return None, _failure(
                preflight, PublicationStatus.ACTIVE_REVISION_CONFLICT, "definition unavailable"
            )
        if row["draft_generation"] != preflight.expected_draft_generation:
            return None, _failure(
                preflight, PublicationStatus.STALE_DRAFT, "draft generation changed"
            )
        if (
            row["active_revision_id"] != preflight.expected_active_revision_id
            or row["active_generation"] != preflight.expected_active_generation
        ):
            return None, _failure(
                preflight, PublicationStatus.ACTIVE_REVISION_CONFLICT, "active pointer changed"
            )
        if row["owner_module_id"] != preflight.expected_base.module_id:
            return None, _failure(
                preflight, PublicationStatus.MODULE_BASE_CHANGED, "canonical base owner changed"
            )
        return row, None

    async def publish(self, preflight: PublishPreflight, ctx: HandlingContext) -> PublicationResult:
        if preflight.target_revision_id is not None:
            return _failure(
                preflight,
                PublicationStatus.INCOMPATIBLE_DEPENDENCY,
                "publish cannot target history",
            )
        row, error = await self._locked_preflight(preflight, ctx)
        if error is not None:
            return error
        assert row is not None
        try:
            snapshot = internal_snapshot(row["draft_snapshot"])
            self._validate_snapshot(snapshot, publishing=True)
        except BusinessOSError:
            return _failure(
                preflight,
                PublicationStatus.CLASSIFICATION_UNAVAILABLE,
                "classification resolver unavailable",
            )
        except ValueError:
            return _failure(
                preflight,
                PublicationStatus.QUOTA_VALIDATION_FAILURE,
                "snapshot invalid or over budget",
            )
        modules = await self._owner_and_dependencies(row, snapshot, ctx)
        if set(modules) != {
            preflight.expected_base.module_id,
            *(item.module_id for item in preflight.dependencies),
        }:
            return _failure(
                preflight, PublicationStatus.INCOMPATIBLE_DEPENDENCY, "dependency set changed"
            )
        tenant_id, principal_id = _tenant(ctx)
        sequence = (
            await ctx.unit_of_work.persistence.execute(
                select(func.coalesce(func.max(REVISIONS.c.sequence), 0) + 1).where(
                    REVISIONS.c.tenant_id == tenant_id,
                    REVISIONS.c.definition_id == preflight.definition_id,
                )
            )
        ).scalar_one()
        revision_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(REVISIONS).values(
                id=revision_id,
                tenant_id=tenant_id,
                definition_id=preflight.definition_id,
                sequence=sequence,
                snapshot=snapshot.model_dump(mode="json"),
                digest=snapshot.digest(),
                schema_generation=preflight.expected_schema_generation,
                ui_generation=preflight.expected_ui_generation,
                published_by=principal_id,
                provenance=ctx.request.correlation_id[:200],
            )
        )
        for expected in sorted(
            (preflight.expected_base, *preflight.dependencies), key=lambda item: item.module_id
        ):
            await ctx.unit_of_work.persistence.execute(
                insert(REVISION_MODULE_BINDINGS).values(
                    tenant_id=tenant_id,
                    revision_id=revision_id,
                    module_id=expected.module_id,
                    artifact_identity=expected.artifact_identity,
                    generation=expected.generation,
                )
            )
        next_generation = row["active_generation"] + 1
        await ctx.unit_of_work.persistence.execute(
            update(DEFINITIONS)
            .where(DEFINITIONS.c.id == preflight.definition_id)
            .values(
                active_revision_id=revision_id,
                active_generation=next_generation,
                lifecycle=DefinitionLifecycle.PUBLISHED.value,
                updated_at=func.now(),
            )
        )
        return PublicationResult(
            status=PublicationStatus.SUCCESS,
            definition_id=preflight.definition_id,
            revision_id=revision_id,
            active_generation=next_generation,
        )

    async def reactivate(
        self, preflight: PublishPreflight, revision_id: UUID, ctx: HandlingContext
    ) -> PublicationResult:
        if preflight.target_revision_id != revision_id:
            return _failure(
                preflight, PublicationStatus.INCOMPATIBLE_DEPENDENCY, "target revision changed"
            )
        row, error = await self._locked_preflight(preflight, ctx)
        if error is not None:
            return error
        assert row is not None
        revision = await self._revision_row(revision_id, preflight.definition_id, ctx)
        if revision is None:
            return _failure(
                preflight, PublicationStatus.INCOMPATIBLE_DEPENDENCY, "revision unavailable"
            )
        try:
            snapshot = internal_snapshot(revision["snapshot"])
            self._validate_snapshot(snapshot, publishing=True)
        except (ValueError, BusinessOSError):
            return _failure(
                preflight,
                PublicationStatus.INCOMPATIBLE_DEPENDENCY,
                "historical schema incompatible",
            )
        modules = await self._owner_and_dependencies(row, snapshot, ctx)
        target_bindings = await self._bindings(revision_id, ctx)
        expected = (preflight.expected_base, *preflight.dependencies)
        if (
            set(modules) != {item.module_id for item in expected}
            or set(target_bindings) != set(expected)
            or revision["schema_generation"] != preflight.expected_schema_generation
            or revision["ui_generation"] != preflight.expected_ui_generation
        ):
            return _failure(
                preflight,
                PublicationStatus.INCOMPATIBLE_DEPENDENCY,
                "historical compatibility changed",
            )
        next_generation = row["active_generation"] + 1
        await ctx.unit_of_work.persistence.execute(
            update(DEFINITIONS)
            .where(DEFINITIONS.c.id == preflight.definition_id)
            .values(
                active_revision_id=revision_id,
                active_generation=next_generation,
                lifecycle=DefinitionLifecycle.PUBLISHED.value,
                updated_at=func.now(),
            )
        )
        return PublicationResult(
            status=PublicationStatus.SUCCESS,
            definition_id=preflight.definition_id,
            revision_id=revision_id,
            active_generation=next_generation,
        )

    async def retire(
        self, cmd: RetireDefinition | RetireCustomEntityDefinition, ctx: HandlingContext
    ) -> DefinitionRecord | CustomEntityDefinitionRecord:
        initial = await self._row(cmd.definition_id, ctx)
        if initial is None:
            raise BusinessOSError("not_found", "Metadata definition not found", status_code=404)
        from .module import RetireCustomEntityDefinition

        self._surface(initial, isinstance(cmd, RetireCustomEntityDefinition))
        if initial["kind"] == "custom_entity":
            tenant_id, _ = _tenant(ctx)
            # Exclusive type coordination pairs with instance shared type locks.
            # Publication does not use it: resolved immutable pins survive races.
            await ctx.unit_of_work.persistence.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"metadata-custom-type:{tenant_id}:{cmd.definition_id}"},
            )
        old_bindings = await self._bindings(initial["active_revision_id"], ctx)
        if old_bindings:
            await ctx.unit_of_work.persistence.execute(
                select(MODULE_FENCE)
                .where(
                    MODULE_FENCE.c.module_id.in_(sorted(item.module_id for item in old_bindings))
                )
                .order_by(MODULE_FENCE.c.module_id)
                .with_for_update()
            )
        row = await self._row(cmd.definition_id, ctx, locked=True)
        if row is None or row["active_generation"] != cmd.expected_active_generation:
            raise BusinessOSError("active_conflict", "Active revision changed", status_code=409)
        await ctx.unit_of_work.persistence.execute(
            update(DEFINITIONS)
            .where(DEFINITIONS.c.id == cmd.definition_id)
            .values(
                active_revision_id=None,
                active_generation=row["active_generation"] + 1,
                lifecycle=DefinitionLifecycle.RETIRED.value,
                updated_at=func.now(),
            )
        )
        updated = await self._row(cmd.definition_id, ctx)
        assert updated is not None
        return _definition(updated)
