"""Metadata Foundation registrations and protected command/query entry points."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import ClassVar
from uuid import UUID

from businessos_audit.v2_contracts import AUDIT_APPENDER_V2, AuditEvidenceV2
from pydantic import ConfigDict, Field

from businessos.sdk import (
    PUBLISHED_CUSTOM_FIELD_SCHEMA,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
)

from .activation_fence import InstallationTransaction, MetadataActivationFence
from .contracts import DefinitionKind, DefinitionSnapshot, MetadataLimits, PublishPreflight
from .custom_schema import PublishedSchemaReader, SchemaReadTransaction
from .store import MetadataStore


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


class MetadataLifecycleEvent(DomainEvent):
    event_type: ClassVar[str] = "metadata.lifecycle.v1"
    definition_id: UUID
    revision_id: UUID | None
    digest: str | None
    action: str
    principal_id: UUID


class MetadataModule:
    version = "1.0"

    def __init__(self, *, limits: MetadataLimits | None = None) -> None:
        data = json.loads(
            files("businessos_metadata").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self._limits = limits or MetadataLimits()
        self._store = MetadataStore(self._limits)
        self._schema_factory: SchemaReadTransaction | None = None
        self._schema_reader: PublishedSchemaReader | None = None

    def _configure_custom_field_reader(self, factory: SchemaReadTransaction) -> None:
        """Private trusted bootstrap composition, not an SDK credential surface."""
        self._schema_factory = factory

    def _activation_fence(self, factory: InstallationTransaction) -> MetadataActivationFence:
        return MetadataActivationFence(factory)

    async def register(self, registration: ModuleRegistration) -> None:
        self._schema_reader = PublishedSchemaReader(self._schema_factory, self._limits)
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
        ):
            registration.permission(PermissionDeclaration(key=key, description=description))
        for contract_id in (
            "foundation.metadata.definition",
            "foundation.metadata.publication",
            "foundation.metadata.reference-resolution",
        ):
            registration.contract(contract_id, self)
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

    async def start(self) -> None:
        if self._schema_reader is not None:
            self._schema_reader.active = True

    async def stop(self) -> None:
        if self._schema_reader is not None:
            self._schema_reader.active = False

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
            revision = await self._store.read_active(cmd.preflight.definition_id, ctx)
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
            revision = await self._store.read_active(cmd.preflight.definition_id, ctx)
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
