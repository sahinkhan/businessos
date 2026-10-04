"""Metadata Foundation registrations and protected command/query entry points."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import ClassVar, Literal, Self
from uuid import UUID

from businessos_audit.v2_contracts import AUDIT_APPENDER_V2, AuditEvidenceV2
from pydantic import ConfigDict, Field, StrictInt, model_validator

from businessos.sdk import (
    PUBLISHED_CUSTOM_FIELD_SCHEMA,
    BusinessOSError,
    Command,
    CustomFieldValue,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
)

from .activation_fence import InstallationTransaction, MetadataActivationFence
from .contracts import DefinitionKind, DefinitionSnapshot, MetadataLimits, PublishPreflight
from .custom_entities import (
    CUSTOM_ENTITY_NAMESPACE,
    CustomEntityLimits,
    CustomEntityQueryCapabilities,
    CustomEntityRecord,
    CustomEntityScopeKind,
)
from .custom_entity_definitions import CustomEntityDefinitionKind, CustomEntityDefinitionSnapshot
from .custom_entity_store import CustomEntityStore
from .custom_schema import (
    PublishedSchemaReader,
    SchemaReadTransaction,
    internal_configure_schema_reader,
    internal_register_schema_reader,
    internal_start_schema_reader,
    internal_stop_schema_reader,
)
from .store import MetadataStore
from .ui_contracts import (
    Locale,
    UIConflict,
    UIOverlayDocument,
    UIOverlayMutationResult,
    UIOverlayScope,
)
from .ui_runtime import PublishedUIRuntime


class ResolvePublishedUI(Query):
    """No caller identity, company, site, permission or arbitrary component authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    locale: Locale


class CreateUIOverlay(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    scope_kind: UIOverlayScope
    document: UIOverlayDocument


class ReadUIOverlay(Query):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1.0"] = "1.0"
    overlay_id: UUID


class _UIOverlayMutation(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1.0"] = "1.0"
    overlay_id: UUID
    expected_draft_generation: StrictInt = Field(ge=1, lt=2**63 - 1)
    expected_active_generation: StrictInt = Field(ge=0, lt=2**63 - 1)


class EditUIOverlay(_UIOverlayMutation):
    document: UIOverlayDocument


class PublishUIOverlay(_UIOverlayMutation):
    pass


class ReactivateUIOverlay(_UIOverlayMutation):
    revision_id: UUID


class RetireUIOverlay(_UIOverlayMutation):
    pass


class UIOverlayChanged(DomainEvent):
    event_type: ClassVar[str] = "metadata.ui-overlay.changed.v1"
    overlay_id: UUID
    view_id: UUID
    revision_id: UUID | None
    active_generation: int
    action: str


class _Input:
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateDefinition(_Input, Command):
    resource_namespace: str
    owner_contract_version: str
    kind: DefinitionKind
    snapshot: DefinitionSnapshot


class EditDraft(_Input, Command):
    definition_id: UUID
    expected_draft_generation: int = Field(ge=1)
    snapshot: DefinitionSnapshot


class PublishDefinition(_Input, Command):
    preflight: PublishPreflight


class ReactivateRevision(_Input, Command):
    preflight: PublishPreflight
    revision_id: UUID


class RetireDefinition(_Input, Command):
    definition_id: UUID
    expected_active_generation: int = Field(ge=0)


class ReadDraft(_Input, Query):
    definition_id: UUID


class ReadActiveRevision(_Input, Query):
    definition_id: UUID


class PreflightPublication(_Input, Query):
    definition_id: UUID
    target_revision_id: UUID | None = None


class CreateCustomEntityDefinition(_Input, Command):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    resource_namespace: str = Field(
        default=CUSTOM_ENTITY_NAMESPACE, pattern=r"^foundation\.metadata\.custom_entity$"
    )
    owner_contract_version: str = Field(default="1", pattern=r"^1$")
    kind: CustomEntityDefinitionKind = CustomEntityDefinitionKind.CUSTOM_ENTITY
    snapshot: CustomEntityDefinitionSnapshot


class EditCustomEntityDraft(_Input, Command):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    definition_id: UUID
    expected_draft_generation: int = Field(ge=1)
    snapshot: CustomEntityDefinitionSnapshot


class ReadCustomEntityDraft(_Input, Query):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    definition_id: UUID


class ReadActiveCustomEntityRevision(ReadCustomEntityDraft):
    pass


class RetireCustomEntityDefinition(_Input, Command):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    definition_id: UUID
    expected_active_generation: int = Field(ge=0)


class _EntityValues(_Input, Command):
    values: tuple[CustomFieldValue, ...] = Field(max_length=1024)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        if len({v.field_id for v in self.values}) != len(self.values):
            raise ValueError("Duplicate stable field IDs")
        return self


class CreateCustomEntity(_EntityValues):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    entity_type_id: UUID
    scope_kind: CustomEntityScopeKind = CustomEntityScopeKind.TENANT


class UpdateCustomEntity(_EntityValues):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    instance_id: UUID
    expected_version: StrictInt = Field(ge=1, lt=2**63 - 1)


class ArchiveCustomEntity(_Input, Command):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    instance_id: UUID
    expected_version: StrictInt = Field(ge=1, lt=2**63 - 1)


class ReadCustomEntity(_Input, Query):
    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    instance_id: UUID
    query_operation: str = Field(default="read", max_length=30)


class ExportCustomEntity(ReadCustomEntity):
    pass


class ListCustomEntities(_Input, Query):
    """Includes current and archived rows in pagination; no lifecycle filter.

    Each record declares lifecycle. Archived rows are immutable and exportable
    under Policy; callers cannot turn this list into a current-only query.
    """

    contract_version: str = Field(default="1.0", pattern=r"^1\.0$")
    entity_type_id: UUID
    scope_kind: CustomEntityScopeKind = CustomEntityScopeKind.TENANT
    page_size: StrictInt = Field(default=50, ge=1, le=1000)
    after: UUID | None = None
    query_operation: str = Field(default="list", max_length=30)


class CustomEntityChanged(DomainEvent):
    event_type: ClassVar[str] = "metadata.custom-entity.changed.v1"
    entity_type_id: UUID
    instance_id: UUID
    revision_id: UUID
    value_version: int
    lifecycle: str
    action: str
    scope_kind: str
    scope_id: UUID


class MetadataLifecycleEvent(DomainEvent):
    event_type: ClassVar[str] = "metadata.lifecycle.v1"
    definition_id: UUID
    revision_id: UUID | None
    digest: str | None
    action: str
    principal_id: UUID


class MetadataModule:
    version = "1.0"

    def __init__(
        self,
        *,
        limits: MetadataLimits | None = None,
        custom_entity_limits: CustomEntityLimits | None = None,
    ) -> None:
        data = json.loads(
            files("businessos_metadata").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self._limits = limits or MetadataLimits()
        self._store = MetadataStore(self._limits)
        self._entities = CustomEntityStore(
            self._limits, custom_entity_limits or CustomEntityLimits()
        )
        self._schema_reader: PublishedSchemaReader | None = None
        self._ui = PublishedUIRuntime()

    def _configure_custom_field_reader(self, factory: SchemaReadTransaction) -> None:
        """Private trusted bootstrap composition, not an SDK credential surface."""
        internal_configure_schema_reader(self, factory)

    def _activation_fence(self, factory: InstallationTransaction) -> MetadataActivationFence:
        return MetadataActivationFence(factory)

    async def register(self, registration: ModuleRegistration) -> None:
        self._schema_reader = internal_register_schema_reader(
            self, registration.generation, self._limits
        )
        reader = self._schema_reader
        registration.dependency(PUBLISHED_CUSTOM_FIELD_SCHEMA, lambda _: reader)
        registration.contract("foundation.metadata.published-custom-field-schema.v1", reader)
        for key, description in (
            ("foundation.metadata.definition.read", "Read published Metadata definitions"),
            ("foundation.metadata.draft.create", "Create Metadata draft"),
            ("foundation.metadata.draft.edit", "Edit Metadata draft"),
            ("foundation.metadata.publish", "Publish Metadata revision"),
            ("foundation.metadata.rollback", "Reactivate Metadata revision"),
            ("foundation.metadata.retire", "Retire Metadata definition"),
            ("foundation.metadata.custom_entity.read", "Read governed custom entities"),
            ("foundation.metadata.custom_entity.create", "Create governed custom entity"),
            ("foundation.metadata.custom_entity.update", "Replace governed custom entity values"),
            ("foundation.metadata.custom_entity.archive", "Archive governed custom entity"),
            ("foundation.metadata.custom_entity.export", "Export one governed custom entity"),
            ("foundation.metadata.ui.read", "Resolve published presentation schema"),
            ("foundation.metadata.ui.draft", "Author bounded presentation overlays"),
            ("foundation.metadata.ui.publish", "Publish bounded presentation overlays"),
            ("foundation.metadata.ui.rollback", "Reactivate compatible presentation overlay"),
            ("foundation.metadata.ui.retire", "Retire presentation overlay"),
        ):
            registration.permission(PermissionDeclaration(key=key, description=description))
        for contract_id in (
            "foundation.metadata.definition",
            "foundation.metadata.publication",
            "foundation.metadata.reference-resolution",
            "foundation.metadata.custom-entity.v1",
            "foundation.metadata.custom-entity-definition.v1",
        ):
            registration.contract(contract_id, self)
        registration.contract(
            "foundation.metadata.custom-entity-query.v1", CustomEntityQueryCapabilities()
        )
        registration.contract("foundation.metadata.published-ui.v1", self._ui)
        registration.query(
            ResolvePublishedUI, self._resolve_ui, permission="foundation.metadata.ui.read"
        )
        registration.query(ReadUIOverlay, self._read_ui, permission="foundation.metadata.ui.draft")
        registration.command(
            CreateUIOverlay, self._create_ui, permission="foundation.metadata.ui.draft"
        )
        registration.command(
            EditUIOverlay, self._edit_ui, permission="foundation.metadata.ui.draft"
        )
        registration.command(
            PublishUIOverlay, self._publish_ui, permission="foundation.metadata.ui.publish"
        )
        registration.command(
            ReactivateUIOverlay, self._reactivate_ui, permission="foundation.metadata.ui.rollback"
        )
        registration.command(
            RetireUIOverlay, self._retire_ui, permission="foundation.metadata.ui.retire"
        )
        registration.command(
            CreateDefinition, self._create, permission="foundation.metadata.draft.create"
        )
        registration.command(EditDraft, self._edit, permission="foundation.metadata.draft.edit")
        registration.command(
            PublishDefinition, self._publish, permission="foundation.metadata.publish"
        )
        registration.command(
            ReactivateRevision, self._reactivate, permission="foundation.metadata.rollback"
        )
        registration.command(
            RetireDefinition, self._retire, permission="foundation.metadata.retire"
        )
        registration.query(ReadDraft, self._read_draft, permission="foundation.metadata.draft.edit")
        registration.query(
            ReadActiveRevision,
            self._read_active,
            permission="foundation.metadata.definition.read",
        )
        registration.query(
            PreflightPublication, self._preflight, permission="foundation.metadata.publish"
        )
        registration.command(
            CreateCustomEntityDefinition,
            self._create_custom_definition,
            permission="foundation.metadata.draft.create",
        )
        registration.command(
            EditCustomEntityDraft,
            self._edit_custom_draft,
            permission="foundation.metadata.draft.edit",
        )
        registration.command(
            RetireCustomEntityDefinition,
            self._retire_custom_definition,
            permission="foundation.metadata.retire",
        )
        registration.query(
            ReadCustomEntityDraft,
            self._read_custom_draft,
            permission="foundation.metadata.draft.edit",
        )
        registration.query(
            ReadActiveCustomEntityRevision,
            self._read_custom_active,
            permission="foundation.metadata.definition.read",
        )
        registration.command(
            CreateCustomEntity,
            self._create_entity,
            permission="foundation.metadata.custom_entity.create",
        )
        registration.command(
            UpdateCustomEntity,
            self._update_entity,
            permission="foundation.metadata.custom_entity.update",
        )
        registration.command(
            ArchiveCustomEntity,
            self._archive_entity,
            permission="foundation.metadata.custom_entity.archive",
        )
        registration.query(
            ReadCustomEntity, self._read_entity, permission="foundation.metadata.custom_entity.read"
        )
        registration.query(
            ListCustomEntities,
            self._list_entities,
            permission="foundation.metadata.custom_entity.read",
        )
        registration.query(
            ExportCustomEntity,
            self._export_entity,
            permission="foundation.metadata.custom_entity.export",
        )

    async def start(self) -> None:
        internal_start_schema_reader(self)

    async def stop(self) -> None:
        internal_stop_schema_reader(self)

    async def _resolve_ui(self, query: ResolvePublishedUI, ctx: HandlingContext) -> object:
        return await self._ui.resolve(query.view_id, query.locale, ctx)

    async def _read_ui(self, query: ReadUIOverlay, ctx: HandlingContext) -> object:
        try:
            return await self._ui.read(query.overlay_id, ctx)
        except UIConflict as error:
            raise BusinessOSError(
                "ui_" + error.code.value, "UI overlay rejected", status_code=409
            ) from None

    async def _create_ui(self, cmd: CreateUIOverlay, ctx: HandlingContext) -> object:
        try:
            record = await self._ui.create(cmd.view_id, cmd.scope_kind, cmd.document, ctx)
        except UIConflict as error:
            raise BusinessOSError(
                "ui_" + error.code.value, "UI overlay rejected", status_code=409
            ) from None
        await self._ui_evidence(record, "create", ctx)
        return record

    async def _edit_ui(self, cmd: EditUIOverlay, ctx: HandlingContext) -> object:
        return await self._mutate_ui(cmd, "edit", ctx)

    async def _publish_ui(self, cmd: PublishUIOverlay, ctx: HandlingContext) -> object:
        return await self._mutate_ui(cmd, "publish", ctx)

    async def _reactivate_ui(self, cmd: ReactivateUIOverlay, ctx: HandlingContext) -> object:
        return await self._mutate_ui(cmd, "reactivate", ctx)

    async def _retire_ui(self, cmd: RetireUIOverlay, ctx: HandlingContext) -> object:
        return await self._mutate_ui(cmd, "retire", ctx)

    async def _mutate_ui(
        self, cmd: _UIOverlayMutation, action: str, ctx: HandlingContext
    ) -> object:
        try:
            record = await self._ui.mutate(
                cmd.overlay_id,
                cmd.expected_draft_generation,
                cmd.expected_active_generation,
                ctx,
                document=cmd.document if isinstance(cmd, EditUIOverlay) else None,
                revision_id=cmd.revision_id if isinstance(cmd, ReactivateUIOverlay) else None,
                retire=isinstance(cmd, RetireUIOverlay),
            )
        except UIConflict as error:
            raise BusinessOSError(
                "ui_" + error.code.value, "UI overlay rejected", status_code=409
            ) from None
        await self._ui_evidence(record, action, ctx)
        return record

    async def _ui_evidence(
        self, record: UIOverlayMutationResult, action: str, ctx: HandlingContext
    ) -> None:
        assert ctx.request.tenant is not None
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        await appender.append(
            AuditEvidenceV2(
                action="metadata.ui-overlay." + action,
                resource_type=record.resource_namespace,
                resource_id=str(record.overlay_id),
                status="success",
                details={
                    "view_id": str(record.view_id),
                    "active_generation": record.active_generation,
                    "revision_id": str(record.active_revision_id)
                    if record.active_revision_id
                    else None,
                },
            ),
            ctx,
        )
        ctx.emit(
            UIOverlayChanged(
                tenant_id=ctx.request.tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                overlay_id=record.overlay_id,
                view_id=record.view_id,
                revision_id=record.active_revision_id,
                active_generation=record.active_generation,
                action=action,
            )
        )

    async def _create_custom_definition(
        self, cmd: CreateCustomEntityDefinition, ctx: HandlingContext
    ) -> object:
        record = await self._store.create(cmd, ctx)
        await self._audit(ctx, "draft.create", record.identity.definition_id, None, None)
        return record

    async def _edit_custom_draft(self, cmd: EditCustomEntityDraft, ctx: HandlingContext) -> object:
        record = await self._store.edit(cmd, ctx)
        await self._audit(ctx, "draft.edit", cmd.definition_id, None, None)
        return record

    async def _retire_custom_definition(
        self, cmd: RetireCustomEntityDefinition, ctx: HandlingContext
    ) -> object:
        record = await self._store.retire(cmd, ctx)
        await self._audit(ctx, "retire", cmd.definition_id, None, None)
        return record

    async def _read_custom_draft(
        self, query: ReadCustomEntityDraft, ctx: HandlingContext
    ) -> object:
        return await self._store.read_draft(query.definition_id, ctx, custom=True)

    async def _read_custom_active(
        self, query: ReadActiveCustomEntityRevision, ctx: HandlingContext
    ) -> object:
        return await self._store.read_active(query.definition_id, ctx, custom=True)

    async def _create(self, cmd: CreateDefinition, ctx: HandlingContext) -> object:
        record = await self._store.create(cmd, ctx)
        await self._audit(ctx, "draft.create", record.identity.definition_id, None, None)
        return record

    async def _edit(self, cmd: EditDraft, ctx: HandlingContext) -> object:
        record = await self._store.edit(cmd, ctx)
        await self._audit(ctx, "draft.edit", cmd.definition_id, None, None)
        return record

    async def _publish(self, cmd: PublishDefinition, ctx: HandlingContext) -> object:
        result = await self._store.publish(cmd.preflight, ctx)
        if result.revision_id is not None:
            revision = await self._store.read_active(
                cmd.preflight.definition_id, ctx, internal=True
            )
            assert revision is not None
            await self._audit(
                ctx, "publish", cmd.preflight.definition_id, revision.revision_id, revision.digest
            )
        else:
            await self._audit(
                ctx,
                "publish",
                cmd.preflight.definition_id,
                None,
                None,
                status=result.status.value,
                emit_event=False,
            )
        return result

    async def _reactivate(self, cmd: ReactivateRevision, ctx: HandlingContext) -> object:
        result = await self._store.reactivate(cmd.preflight, cmd.revision_id, ctx)
        if result.revision_id is not None:
            revision = await self._store.read_active(
                cmd.preflight.definition_id, ctx, internal=True
            )
            assert revision is not None
            await self._audit(
                ctx,
                "reactivate",
                cmd.preflight.definition_id,
                revision.revision_id,
                revision.digest,
            )
        else:
            await self._audit(
                ctx,
                "reactivate",
                cmd.preflight.definition_id,
                None,
                None,
                status=result.status.value,
                emit_event=False,
            )
        return result

    async def _retire(self, cmd: RetireDefinition, ctx: HandlingContext) -> object:
        record = await self._store.retire(cmd, ctx)
        await self._audit(ctx, "retire", cmd.definition_id, None, None)
        return record

    async def _read_draft(self, query: ReadDraft, ctx: HandlingContext) -> object:
        return await self._store.read_draft(query.definition_id, ctx)

    async def _read_active(self, query: ReadActiveRevision, ctx: HandlingContext) -> object:
        return await self._store.read_active(query.definition_id, ctx)

    async def _preflight(self, query: PreflightPublication, ctx: HandlingContext) -> object:
        return await self._store.preflight(query.definition_id, query.target_revision_id, ctx)

    async def _create_entity(self, cmd: CreateCustomEntity, ctx: HandlingContext) -> object:
        record = await self._entities.create(cmd, ctx)
        await self._entity_evidence(record, "create", ctx)
        return record

    async def _update_entity(self, cmd: UpdateCustomEntity, ctx: HandlingContext) -> object:
        record = await self._entities.mutate(cmd, ctx, archive=False)
        await self._entity_evidence(record, "update", ctx)
        return record

    async def _archive_entity(self, cmd: ArchiveCustomEntity, ctx: HandlingContext) -> object:
        record = await self._entities.mutate(cmd, ctx, archive=True)
        await self._entity_evidence(record, "archive", ctx)
        return record

    async def _read_entity(self, query: ReadCustomEntity, ctx: HandlingContext) -> object:
        CustomEntityQueryCapabilities().require(query.query_operation)
        return await self._entities.read(query.instance_id, ctx)

    async def _list_entities(self, query: ListCustomEntities, ctx: HandlingContext) -> object:
        CustomEntityQueryCapabilities().require(query.query_operation)
        return await self._entities.list(query, ctx)

    async def _export_entity(self, query: ExportCustomEntity, ctx: HandlingContext) -> object:
        CustomEntityQueryCapabilities().require(query.query_operation)
        return await self._entities.export(query.instance_id, ctx)

    async def _entity_evidence(
        self, record: CustomEntityRecord, action: str, ctx: HandlingContext
    ) -> None:
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        facts = {
            "entity_type_id": str(record.identity.entity_type_id),
            "revision_id": str(record.revision_id),
            "value_version": record.value_version,
            "lifecycle": record.lifecycle.value,
            "scope_kind": record.scope_kind.value,
            "scope_id": str(record.scope_id),
            "correlation_id": ctx.request.correlation_id,
        }
        await appender.append(
            AuditEvidenceV2(
                action=f"metadata.custom-entity.{action}",
                resource_type=CUSTOM_ENTITY_NAMESPACE,
                resource_id=str(record.identity.instance_id),
                status="success",
                details=facts,
            ),
            ctx,
        )
        ctx.emit(
            CustomEntityChanged(
                tenant_id=record.identity.tenant_id,
                correlation_id=ctx.request.correlation_id,
                entity_type_id=record.identity.entity_type_id,
                instance_id=record.identity.instance_id,
                revision_id=record.revision_id,
                value_version=record.value_version,
                lifecycle=record.lifecycle.value,
                scope_kind=record.scope_kind.value,
                scope_id=record.scope_id,
                action=action,
            )
        )

    async def _audit(
        self,
        ctx: HandlingContext,
        action: str,
        definition_id: UUID,
        revision_id: UUID | None,
        digest: str | None,
        *,
        status: str = "success",
        emit_event: bool = True,
    ) -> None:
        tenant = ctx.request.tenant
        if tenant is None:
            raise PermissionError("Trusted tenant required")
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        await appender.append(
            AuditEvidenceV2(
                action=f"metadata.{action}",
                resource_type="foundation.metadata.definition",
                resource_id=str(definition_id),
                status=status,
                details={
                    "revision_id": str(revision_id) if revision_id else None,
                    "digest": digest,
                    "correlation_id": ctx.request.correlation_id,
                },
            ),
            ctx,
        )
        if emit_event:
            ctx.emit(
                MetadataLifecycleEvent(
                    tenant_id=tenant.tenant_id,
                    correlation_id=ctx.request.correlation_id,
                    definition_id=definition_id,
                    revision_id=revision_id,
                    digest=digest,
                    action=action,
                    principal_id=tenant.principal_id,
                )
            )
