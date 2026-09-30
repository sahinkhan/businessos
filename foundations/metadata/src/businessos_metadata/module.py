"""Platform Foundation Metadata module registration and command/query handlers."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any
from uuid import UUID

from businessos.sdk import (
    BusinessOSError,
    DependencyScope,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    RequestContext,
    TenantContext,
)

from .contracts import (
    METADATA_DEFINITION_CONTRACT_V1,
    METADATA_DEFINITION_SERVICE_V1,
    METADATA_PUBLICATION_FENCE_CONTRACT_V1,
    METADATA_PUBLICATION_FENCE_SERVICE_V1,
    METADATA_PUBLISH_CONTRACT_V1,
    METADATA_PUBLISH_SERVICE_V1,
    METADATA_REVISION_CONTRACT_V1,
    METADATA_REVISION_SERVICE_V1,
    METADATA_ROLLBACK_CONTRACT_V1,
    METADATA_ROLLBACK_SERVICE_V1,
    REFERENCE_RESOLUTION_CONTRACT_V1,
    REFERENCE_RESOLUTION_SERVICE_V1,
    VALIDATION_GRAMMAR_CONTRACT_V1,
    VALIDATION_GRAMMAR_SERVICE_V1,
    CreateDraftDefinitionCommand,
    GetActiveRevisionQuery,
    GetDefinitionQuery,
    GetPublishedDefinitionQuery,
    GetRevisionByIdQuery,
    ListDefinitionsQuery,
    ListRevisionsQuery,
    MetadataDefinitionRecord,
    MetadataRevisionRecord,
    PublishDraftCommand,
    PublishResult,
    RetireDefinitionCommand,
    RollbackResult,
    RollbackRevisionCommand,
    UpdateDraftDefinitionCommand,
)
from .service import MetadataService


def _require_tenant(request: RequestContext | None) -> TenantContext:
    if request is None or request.tenant is None:
        raise BusinessOSError(
            "tenant_context_required", "Tenant context is required", status_code=401
        )
    return request.tenant


class MetadataModule:
    """Platform Foundation Metadata and Studio definition foundation module."""

    def __init__(self) -> None:
        manifest_raw = json.loads(
            files("businessos_metadata").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(manifest_raw)
        self.service = MetadataService()

    async def register(self, registration: ModuleRegistration) -> None:
        # Public contracts
        registration.contract(METADATA_DEFINITION_CONTRACT_V1, self.service)
        registration.contract(METADATA_REVISION_CONTRACT_V1, self.service)
        registration.contract(METADATA_PUBLISH_CONTRACT_V1, self.service)
        registration.contract(METADATA_ROLLBACK_CONTRACT_V1, self.service)
        registration.contract(VALIDATION_GRAMMAR_CONTRACT_V1, self.service)
        registration.contract(REFERENCE_RESOLUTION_CONTRACT_V1, self.service)
        registration.contract(METADATA_PUBLICATION_FENCE_CONTRACT_V1, self.service)

        # DI Dependencies
        registration.dependency(
            METADATA_DEFINITION_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            METADATA_REVISION_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            METADATA_PUBLISH_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            METADATA_ROLLBACK_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            VALIDATION_GRAMMAR_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            REFERENCE_RESOLUTION_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            METADATA_PUBLICATION_FENCE_SERVICE_V1,
            lambda _: self.service,
            scope=DependencyScope.SINGLETON,
        )

        # Permissions
        registration.permission(
            PermissionDeclaration(
                key="foundation.metadata.read",
                description="Read metadata definitions and published revisions",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.metadata.draft.write",
                description="Create and modify metadata drafts",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.metadata.publish",
                description="Publish metadata drafts to immutable revisions",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.metadata.rollback",
                description="Reactivate historical metadata revisions",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.metadata.retire",
                description="Retire or archive metadata definitions",
            )
        )

        # Commands
        registration.command(
            CreateDraftDefinitionCommand,
            self._handle_create_draft,
            permission="foundation.metadata.draft.write",
        )
        registration.command(
            UpdateDraftDefinitionCommand,
            self._handle_update_draft,
            permission="foundation.metadata.draft.write",
        )
        registration.command(
            PublishDraftCommand,
            self._handle_publish_draft,
            permission="foundation.metadata.publish",
        )
        registration.command(
            RollbackRevisionCommand,
            self._handle_rollback_revision,
            permission="foundation.metadata.rollback",
        )
        registration.command(
            RetireDefinitionCommand,
            self._handle_retire_definition,
            permission="foundation.metadata.retire",
        )

        # Queries
        registration.query(
            GetDefinitionQuery,
            self._handle_get_definition,
            permission="foundation.metadata.read",
        )
        registration.query(
            GetPublishedDefinitionQuery,
            self._handle_get_published_definition,
            permission="foundation.metadata.read",
        )
        registration.query(
            ListDefinitionsQuery,
            self._handle_list_definitions,
            permission="foundation.metadata.read",
        )
        registration.query(
            GetActiveRevisionQuery,
            self._handle_get_active_revision,
            permission="foundation.metadata.read",
        )
        registration.query(
            GetRevisionByIdQuery,
            self._handle_get_revision_by_id,
            permission="foundation.metadata.read",
        )
        registration.query(
            ListRevisionsQuery,
            self._handle_list_revisions,
            permission="foundation.metadata.read",
        )

    # --- Handlers ---

    async def _handle_create_draft(
        self, cmd: CreateDraftDefinitionCommand, ctx: HandlingContext
    ) -> MetadataDefinitionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.create_draft(
            tenant_id=tenant.tenant_id,
            owner_namespace=cmd.owner_namespace,
            definition_kind=cmd.definition_kind,
            stable_key=cmd.stable_key,
            payload=cmd.payload,
            created_by=str(tenant.principal_id),
            ctx=ctx,
        )

    async def _handle_update_draft(
        self, cmd: UpdateDraftDefinitionCommand, ctx: HandlingContext
    ) -> MetadataDefinitionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.update_draft(
            tenant_id=tenant.tenant_id,
            definition_id=cmd.definition_id,
            expected_draft_generation=cmd.expected_draft_generation,
            payload=cmd.payload,
            updated_by=str(tenant.principal_id),
            ctx=ctx,
        )

    async def _handle_publish_draft(
        self, cmd: PublishDraftCommand, ctx: HandlingContext
    ) -> PublishResult:
        tenant = _require_tenant(ctx.request)
        return await self.service.publish(
            tenant_id=tenant.tenant_id,
            definition_id=cmd.definition_id,
            preflight=cmd.preflight,
            published_by=str(tenant.principal_id),
            comment=cmd.comment,
            ctx=ctx,
        )

    async def _handle_rollback_revision(
        self, cmd: RollbackRevisionCommand, ctx: HandlingContext
    ) -> RollbackResult:
        tenant = _require_tenant(ctx.request)
        return await self.service.rollback(
            tenant_id=tenant.tenant_id,
            definition_id=cmd.definition_id,
            target_revision_id=cmd.target_revision_id,
            preflight=cmd.preflight,
            reactivated_by=str(tenant.principal_id),
            comment=cmd.comment,
            ctx=ctx,
        )

    async def _handle_retire_definition(
        self, cmd: RetireDefinitionCommand, ctx: HandlingContext
    ) -> MetadataDefinitionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.retire(
            tenant_id=tenant.tenant_id,
            definition_id=cmd.definition_id,
            retired_by=str(tenant.principal_id),
            ctx=ctx,
        )

    async def _handle_get_definition(
        self, q: GetDefinitionQuery, ctx: HandlingContext
    ) -> MetadataDefinitionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.get_definition(
            tenant_id=tenant.tenant_id,
            definition_id=q.definition_id,
            executor=ctx.unit_of_work.persistence,
        )

    async def _handle_get_published_definition(
        self, q: GetPublishedDefinitionQuery, ctx: HandlingContext
    ) -> tuple[MetadataDefinitionRecord, MetadataRevisionRecord]:
        tenant = _require_tenant(ctx.request)
        return await self.service.get_published_definition(
            tenant_id=tenant.tenant_id,
            owner_namespace=q.owner_namespace,
            definition_kind=q.definition_kind,
            stable_key=q.stable_key,
            executor=ctx.unit_of_work.persistence,
        )

    async def _handle_list_definitions(
        self, q: ListDefinitionsQuery, ctx: HandlingContext
    ) -> tuple[MetadataDefinitionRecord, ...]:
        tenant = _require_tenant(ctx.request)
        return await self.service.list_definitions(
            tenant_id=tenant.tenant_id,
            owner_namespace=q.owner_namespace,
            definition_kind=q.definition_kind,
            status=q.status,
            executor=ctx.unit_of_work.persistence,
        )

    async def _handle_get_active_revision(
        self, q: GetActiveRevisionQuery, ctx: HandlingContext
    ) -> MetadataRevisionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.get_active_revision(
            tenant_id=tenant.tenant_id,
            definition_id=q.definition_id,
            executor=ctx.unit_of_work.persistence,
        )

    async def _handle_get_revision_by_id(
        self, q: GetRevisionByIdQuery, ctx: HandlingContext
    ) -> MetadataRevisionRecord:
        tenant = _require_tenant(ctx.request)
        return await self.service.get_revision_by_id(
            tenant_id=tenant.tenant_id,
            definition_id=q.definition_id,
            revision_id=q.revision_id,
            executor=ctx.unit_of_work.persistence,
        )

    async def _handle_list_revisions(
        self, q: ListRevisionsQuery, ctx: HandlingContext
    ) -> tuple[MetadataRevisionRecord, ...]:
        tenant = _require_tenant(ctx.request)
        return await self.service.list_revisions(
            tenant_id=tenant.tenant_id,
            definition_id=q.definition_id,
            executor=ctx.unit_of_work.persistence,
        )
