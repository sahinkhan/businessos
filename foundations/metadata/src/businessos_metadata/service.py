"""Metadata runtime implementation of definition, revision, publish, rollback, and reference contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert

from businessos.contracts import PublicContract
from businessos.sdk import BusinessOSError, HandlingContext

from .contracts import (
    MetadataActivePointerRecord,
    MetadataDefinitionContractV1,
    MetadataDefinitionRecord,
    MetadataDraftCreated,
    MetadataDraftUpdated,
    MetadataLifecycleStatus,
    MetadataPublicationFenceContractV1,
    MetadataPublishContractV1,
    MetadataRevisionContractV1,
    MetadataRevisionProvenance,
    MetadataRevisionPublished,
    MetadataRevisionReactivated,
    MetadataRevisionRecord,
    MetadataRollbackContractV1,
    PublishPreflightInput,
    PublishPreflightResult,
    PublishResult,
    PublishStatus,
    ReferenceResolutionContractV1,
    RollbackPreflightInput,
    RollbackPreflightResult,
    RollbackResult,
    RollbackStatus,
    ValidationGrammarContractV1,
)
from .diagnostics import MetadataDiagnosticCode, MetadataDiagnosticError, MetadataDiagnosticRecord
from .fence import (
    FenceStateRecord,
    acquire_fence_for_publication,
    advance_fence_publication,
    get_or_create_fence,
)
from .grammar import (
    MAX_BULK_REFERENCE_BATCH,
    MAX_DEFINITIONS_PER_TENANT,
    MetadataPayloadModel,
)
from .models import (
    METADATA_ACTIVE_POINTERS,
    METADATA_DEFINITIONS,
    METADATA_PUBLICATION_FENCES,
    METADATA_REVISIONS,
)
from .references import (
    BulkReferenceResolutionQuery,
    ReferenceResolutionQuery,
    ReferenceResolutionRecord,
    ReferenceResolutionResult,
    TargetReferenceState,
    validate_cross_owner_deletion,
)


def _compute_digest(payload: dict[str, Any]) -> str:
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()


class MetadataService(
    MetadataDefinitionContractV1,
    MetadataRevisionContractV1,
    MetadataPublishContractV1,
    MetadataRollbackContractV1,
    ValidationGrammarContractV1,
    ReferenceResolutionContractV1,
    MetadataPublicationFenceContractV1,
):
    """Platform Foundation service providing persistent metadata definitions, revisions, and serialization fence."""

    def __init__(self, db_executor_factory: Any | None = None) -> None:
        self._db_executor_factory = db_executor_factory

    @property
    def version(self) -> str:
        return "1"

    # --- Validation Grammar ---

    def validate_payload(self, payload: dict[str, Any] | MetadataPayloadModel) -> MetadataPayloadModel:
        if isinstance(payload, MetadataPayloadModel):
            return payload
        return MetadataPayloadModel.model_validate(payload)

    # --- Definition Lifecycle ---

    async def create_draft(
        self,
        tenant_id: UUID,
        owner_namespace: str,
        definition_kind: str,
        stable_key: str,
        payload: MetadataPayloadModel,
        created_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord:
        executor = self._get_executor(ctx)

        # Tenant definition quota check
        count_stmt = select(METADATA_DEFINITIONS.c.id).where(
            METADATA_DEFINITIONS.c.tenant_id == tenant_id
        )
        existing_rows = (await executor.execute(count_stmt)).all()
        if len(existing_rows) >= MAX_DEFINITIONS_PER_TENANT:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Tenant {tenant_id} has reached the maximum definition quota ({MAX_DEFINITIONS_PER_TENANT})",
                details={"quota": "max_definitions", "limit": MAX_DEFINITIONS_PER_TENANT},
            )

        definition_id = uuid4()
        now = datetime.now(UTC)
        validated_payload = self.validate_payload(payload).model_dump(mode="json")

        stmt = (
            insert(METADATA_DEFINITIONS)
            .values(
                id=definition_id,
                tenant_id=tenant_id,
                owner_namespace=owner_namespace,
                definition_kind=definition_kind,
                stable_key=stable_key,
                lifecycle_status=MetadataLifecycleStatus.DRAFT.value,
                draft_generation=1,
                draft_payload=validated_payload,
                active_revision_id=None,
                active_generation=0,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            .returning(
                METADATA_DEFINITIONS.c.id,
                METADATA_DEFINITIONS.c.tenant_id,
                METADATA_DEFINITIONS.c.owner_namespace,
                METADATA_DEFINITIONS.c.definition_kind,
                METADATA_DEFINITIONS.c.stable_key,
                METADATA_DEFINITIONS.c.lifecycle_status,
                METADATA_DEFINITIONS.c.draft_generation,
                METADATA_DEFINITIONS.c.draft_payload,
                METADATA_DEFINITIONS.c.active_revision_id,
                METADATA_DEFINITIONS.c.active_generation,
                METADATA_DEFINITIONS.c.created_by,
                METADATA_DEFINITIONS.c.created_at,
                METADATA_DEFINITIONS.c.updated_at,
            )
        )
        result = await executor.execute(stmt)
        row = result.mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED, "Failed to create draft definition"
            )

        record = MetadataDefinitionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            owner_namespace=row["owner_namespace"],
            definition_kind=row["definition_kind"],
            stable_key=row["stable_key"],
            lifecycle_status=MetadataLifecycleStatus(row["lifecycle_status"]),
            draft_generation=row["draft_generation"],
            draft_payload=row["draft_payload"],
            active_revision_id=row["active_revision_id"],
            active_generation=row["active_generation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

        if ctx is not None and hasattr(ctx, "emit") and ctx.request.tenant is not None:
            ctx.emit(
                MetadataDraftCreated(
                    tenant_id=tenant_id,
                    correlation_id=ctx.request.correlation_id,
                    definition_id=definition_id,
                    owner_namespace=owner_namespace,
                    definition_kind=definition_kind,
                    stable_key=stable_key,
                    draft_generation=1,
                )
            )

        return record

    async def update_draft(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        expected_draft_generation: int,
        payload: MetadataPayloadModel,
        updated_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord:
        executor = self._get_executor(ctx)
        validated_payload = self.validate_payload(payload).model_dump(mode="json")
        now = datetime.now(UTC)

        # Lock definition row
        lock_stmt = (
            select(METADATA_DEFINITIONS)
            .where(
                METADATA_DEFINITIONS.c.id == definition_id,
                METADATA_DEFINITIONS.c.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        row = (await executor.execute(lock_stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"Metadata definition '{definition_id}' not found for tenant",
                status_code=404,
            )

        if row["draft_generation"] != expected_draft_generation:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.STALE_DRAFT,
                f"Draft generation conflict on definition '{definition_id}': expected {expected_draft_generation}, current {row['draft_generation']}",
                details={"expected": expected_draft_generation, "actual": row["draft_generation"]},
            )

        if row["lifecycle_status"] in (MetadataLifecycleStatus.RETIRED.value, MetadataLifecycleStatus.ARCHIVED.value):
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"Cannot update draft of {row['lifecycle_status']} definition '{definition_id}'",
            )

        new_draft_gen = row["draft_generation"] + 1
        update_stmt = (
            METADATA_DEFINITIONS.update()
            .where(
                METADATA_DEFINITIONS.c.id == definition_id,
                METADATA_DEFINITIONS.c.tenant_id == tenant_id,
            )
            .values(
                draft_generation=new_draft_gen,
                draft_payload=validated_payload,
                lifecycle_status=MetadataLifecycleStatus.DRAFT.value,
                updated_at=now,
            )
            .returning(
                METADATA_DEFINITIONS.c.id,
                METADATA_DEFINITIONS.c.tenant_id,
                METADATA_DEFINITIONS.c.owner_namespace,
                METADATA_DEFINITIONS.c.definition_kind,
                METADATA_DEFINITIONS.c.stable_key,
                METADATA_DEFINITIONS.c.lifecycle_status,
                METADATA_DEFINITIONS.c.draft_generation,
                METADATA_DEFINITIONS.c.draft_payload,
                METADATA_DEFINITIONS.c.active_revision_id,
                METADATA_DEFINITIONS.c.active_generation,
                METADATA_DEFINITIONS.c.created_by,
                METADATA_DEFINITIONS.c.created_at,
                METADATA_DEFINITIONS.c.updated_at,
            )
        )
        updated_row = (await executor.execute(update_stmt)).mappings().first()
        assert updated_row is not None

        record = MetadataDefinitionRecord(
            id=updated_row["id"],
            tenant_id=updated_row["tenant_id"],
            owner_namespace=updated_row["owner_namespace"],
            definition_kind=updated_row["definition_kind"],
            stable_key=updated_row["stable_key"],
            lifecycle_status=MetadataLifecycleStatus(updated_row["lifecycle_status"]),
            draft_generation=updated_row["draft_generation"],
            draft_payload=updated_row["draft_payload"],
            active_revision_id=updated_row["active_revision_id"],
            active_generation=updated_row["active_generation"],
            created_by=updated_row["created_by"],
            created_at=updated_row["created_at"],
            updated_at=updated_row["updated_at"],
        )

        if ctx is not None and hasattr(ctx, "emit") and ctx.request.tenant is not None:
            ctx.emit(
                MetadataDraftUpdated(
                    tenant_id=tenant_id,
                    correlation_id=ctx.request.correlation_id,
                    definition_id=definition_id,
                    draft_generation=new_draft_gen,
                )
            )

        return record

    async def get_definition(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataDefinitionRecord:
        exec_ctx = executor or self._get_executor()
        stmt = select(METADATA_DEFINITIONS).where(
            METADATA_DEFINITIONS.c.id == definition_id,
            METADATA_DEFINITIONS.c.tenant_id == tenant_id,
        )
        row = (await exec_ctx.execute(stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"Definition '{definition_id}' not found",
                status_code=404,
            )
        return MetadataDefinitionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            owner_namespace=row["owner_namespace"],
            definition_kind=row["definition_kind"],
            stable_key=row["stable_key"],
            lifecycle_status=MetadataLifecycleStatus(row["lifecycle_status"]),
            draft_generation=row["draft_generation"],
            draft_payload=row["draft_payload"],
            active_revision_id=row["active_revision_id"],
            active_generation=row["active_generation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_published_definition(
        self,
        tenant_id: UUID,
        owner_namespace: str,
        definition_kind: str,
        stable_key: str,
        *,
        executor: Any = None,
    ) -> tuple[MetadataDefinitionRecord, MetadataRevisionRecord]:
        """Published-only read invariant. Draft state is never returned."""
        exec_ctx = executor or self._get_executor()
        stmt = (
            select(METADATA_DEFINITIONS, METADATA_REVISIONS)
            .join(
                METADATA_ACTIVE_POINTERS,
                (METADATA_ACTIVE_POINTERS.c.definition_id == METADATA_DEFINITIONS.c.id)
                & (METADATA_ACTIVE_POINTERS.c.tenant_id == METADATA_DEFINITIONS.c.tenant_id),
            )
            .join(
                METADATA_REVISIONS,
                (METADATA_REVISIONS.c.id == METADATA_ACTIVE_POINTERS.c.revision_id)
                & (METADATA_REVISIONS.c.tenant_id == METADATA_ACTIVE_POINTERS.c.tenant_id),
            )
            .where(
                METADATA_DEFINITIONS.c.tenant_id == tenant_id,
                METADATA_DEFINITIONS.c.owner_namespace == owner_namespace,
                METADATA_DEFINITIONS.c.definition_kind == definition_kind,
                METADATA_DEFINITIONS.c.stable_key == stable_key,
                METADATA_DEFINITIONS.c.lifecycle_status == MetadataLifecycleStatus.PUBLISHED.value,
            )
        )
        row = (await exec_ctx.execute(stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"No active published definition found for {owner_namespace}:{definition_kind}:{stable_key}",
                status_code=404,
            )

        def_record = MetadataDefinitionRecord(
            id=row[METADATA_DEFINITIONS.c.id],
            tenant_id=row[METADATA_DEFINITIONS.c.tenant_id],
            owner_namespace=row[METADATA_DEFINITIONS.c.owner_namespace],
            definition_kind=row[METADATA_DEFINITIONS.c.definition_kind],
            stable_key=row[METADATA_DEFINITIONS.c.stable_key],
            lifecycle_status=MetadataLifecycleStatus(row[METADATA_DEFINITIONS.c.lifecycle_status]),
            draft_generation=row[METADATA_DEFINITIONS.c.draft_generation],
            draft_payload=None,  # Do not leak draft payload on published read!
            active_revision_id=row[METADATA_DEFINITIONS.c.active_revision_id],
            active_generation=row[METADATA_DEFINITIONS.c.active_generation],
            created_by=row[METADATA_DEFINITIONS.c.created_by],
            created_at=row[METADATA_DEFINITIONS.c.created_at],
            updated_at=row[METADATA_DEFINITIONS.c.updated_at],
        )

        rev_record = MetadataRevisionRecord(
            id=row[METADATA_REVISIONS.c.id],
            tenant_id=row[METADATA_REVISIONS.c.tenant_id],
            definition_id=row[METADATA_REVISIONS.c.definition_id],
            revision_seq=row[METADATA_REVISIONS.c.revision_seq],
            schema_version=row[METADATA_REVISIONS.c.schema_version],
            content_digest=row[METADATA_REVISIONS.c.content_digest],
            payload=row[METADATA_REVISIONS.c.payload],
            provenance=MetadataRevisionProvenance.model_validate(row[METADATA_REVISIONS.c.provenance]),
            created_at=row[METADATA_REVISIONS.c.created_at],
        )
        return def_record, rev_record

    async def list_definitions(
        self,
        tenant_id: UUID,
        owner_namespace: str | None = None,
        definition_kind: str | None = None,
        status: MetadataLifecycleStatus | None = None,
        *,
        executor: Any = None,
    ) -> tuple[MetadataDefinitionRecord, ...]:
        exec_ctx = executor or self._get_executor()
        stmt = select(METADATA_DEFINITIONS).where(METADATA_DEFINITIONS.c.tenant_id == tenant_id)
        if owner_namespace is not None:
            stmt = stmt.where(METADATA_DEFINITIONS.c.owner_namespace == owner_namespace)
        if definition_kind is not None:
            stmt = stmt.where(METADATA_DEFINITIONS.c.definition_kind == definition_kind)
        if status is not None:
            stmt = stmt.where(METADATA_DEFINITIONS.c.lifecycle_status == status.value)

        rows = (await exec_ctx.execute(stmt)).mappings().all()
        return tuple(
            MetadataDefinitionRecord(
                id=r["id"],
                tenant_id=r["tenant_id"],
                owner_namespace=r["owner_namespace"],
                definition_kind=r["definition_kind"],
                stable_key=r["stable_key"],
                lifecycle_status=MetadataLifecycleStatus(r["lifecycle_status"]),
                draft_generation=r["draft_generation"],
                draft_payload=r["draft_payload"],
                active_revision_id=r["active_revision_id"],
                active_generation=r["active_generation"],
                created_by=r["created_by"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        )

    async def retire(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        retired_by: str,
        *,
        ctx: Any = None,
    ) -> MetadataDefinitionRecord:
        executor = self._get_executor(ctx)
        now = datetime.now(UTC)

        stmt = (
            METADATA_DEFINITIONS.update()
            .where(
                METADATA_DEFINITIONS.c.id == definition_id,
                METADATA_DEFINITIONS.c.tenant_id == tenant_id,
            )
            .values(
                lifecycle_status=MetadataLifecycleStatus.RETIRED.value,
                updated_at=now,
            )
            .returning(
                METADATA_DEFINITIONS.c.id,
                METADATA_DEFINITIONS.c.tenant_id,
                METADATA_DEFINITIONS.c.owner_namespace,
                METADATA_DEFINITIONS.c.definition_kind,
                METADATA_DEFINITIONS.c.stable_key,
                METADATA_DEFINITIONS.c.lifecycle_status,
                METADATA_DEFINITIONS.c.draft_generation,
                METADATA_DEFINITIONS.c.draft_payload,
                METADATA_DEFINITIONS.c.active_revision_id,
                METADATA_DEFINITIONS.c.active_generation,
                METADATA_DEFINITIONS.c.created_by,
                METADATA_DEFINITIONS.c.created_at,
                METADATA_DEFINITIONS.c.updated_at,
            )
        )
        row = (await executor.execute(stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"Definition '{definition_id}' not found for retire",
                status_code=404,
            )

        record = MetadataDefinitionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            owner_namespace=row["owner_namespace"],
            definition_kind=row["definition_kind"],
            stable_key=row["stable_key"],
            lifecycle_status=MetadataLifecycleStatus(row["lifecycle_status"]),
            draft_generation=row["draft_generation"],
            draft_payload=row["draft_payload"],
            active_revision_id=row["active_revision_id"],
            active_generation=row["active_generation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

        if ctx is not None and hasattr(ctx, "emit") and ctx.request.tenant is not None:
            ctx.emit(
                MetadataDefinitionRetired(
                    tenant_id=tenant_id,
                    correlation_id=ctx.request.correlation_id,
                    definition_id=definition_id,
                    retired_by=retired_by,
                )
            )

        return record

    # --- Revision Queries ---

    async def get_active_revision(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataRevisionRecord:
        exec_ctx = executor or self._get_executor()
        stmt = (
            select(METADATA_REVISIONS)
            .join(
                METADATA_ACTIVE_POINTERS,
                (METADATA_ACTIVE_POINTERS.c.revision_id == METADATA_REVISIONS.c.id)
                & (METADATA_ACTIVE_POINTERS.c.tenant_id == METADATA_REVISIONS.c.tenant_id),
            )
            .where(
                METADATA_ACTIVE_POINTERS.c.tenant_id == tenant_id,
                METADATA_ACTIVE_POINTERS.c.definition_id == definition_id,
            )
        )
        row = (await exec_ctx.execute(stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.REVISION_NOT_FOUND,
                f"No active revision found for definition '{definition_id}'",
                status_code=404,
            )
        return MetadataRevisionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            definition_id=row["definition_id"],
            revision_seq=row["revision_seq"],
            schema_version=row["schema_version"],
            content_digest=row["content_digest"],
            payload=row["payload"],
            provenance=MetadataRevisionProvenance.model_validate(row["provenance"]),
            created_at=row["created_at"],
        )

    async def get_revision_by_id(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        revision_id: UUID,
        *,
        executor: Any = None,
    ) -> MetadataRevisionRecord:
        exec_ctx = executor or self._get_executor()
        stmt = select(METADATA_REVISIONS).where(
            METADATA_REVISIONS.c.id == revision_id,
            METADATA_REVISIONS.c.definition_id == definition_id,
            METADATA_REVISIONS.c.tenant_id == tenant_id,
        )
        row = (await exec_ctx.execute(stmt)).mappings().first()
        if row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.REVISION_NOT_FOUND,
                f"Revision '{revision_id}' not found for definition '{definition_id}'",
                status_code=404,
            )
        return MetadataRevisionRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            definition_id=row["definition_id"],
            revision_seq=row["revision_seq"],
            schema_version=row["schema_version"],
            content_digest=row["content_digest"],
            payload=row["payload"],
            provenance=MetadataRevisionProvenance.model_validate(row["provenance"]),
            created_at=row["created_at"],
        )

    async def list_revisions(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        *,
        executor: Any = None,
    ) -> tuple[MetadataRevisionRecord, ...]:
        exec_ctx = executor or self._get_executor()
        stmt = (
            select(METADATA_REVISIONS)
            .where(
                METADATA_REVISIONS.c.tenant_id == tenant_id,
                METADATA_REVISIONS.c.definition_id == definition_id,
            )
            .order_by(desc(METADATA_REVISIONS.c.revision_seq))
        )
        rows = (await exec_ctx.execute(stmt)).mappings().all()
        return tuple(
            MetadataRevisionRecord(
                id=r["id"],
                tenant_id=r["tenant_id"],
                definition_id=r["definition_id"],
                revision_seq=r["revision_seq"],
                schema_version=r["schema_version"],
                content_digest=r["content_digest"],
                payload=r["payload"],
                provenance=MetadataRevisionProvenance.model_validate(r["provenance"]),
                created_at=r["created_at"],
            )
            for r in rows
        )

    # --- Publication & Preflight ---

    async def preflight(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> PublishPreflightResult:
        exec_ctx = executor or self._get_executor()

        # Read definition
        def_stmt = select(METADATA_DEFINITIONS).where(
            METADATA_DEFINITIONS.c.id == definition_id,
            METADATA_DEFINITIONS.c.tenant_id == tenant_id,
        )
        def_row = (await exec_ctx.execute(def_stmt)).mappings().first()
        if def_row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.POLICY_DENIED,
                f"Definition '{definition_id}' not found for preflight",
                status_code=404,
            )

        if not def_row["draft_payload"]:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED,
                f"Definition '{definition_id}' has no draft payload to publish",
            )

        # Validate draft grammar & quotas
        self.validate_payload(def_row["draft_payload"])

        fence = await get_or_create_fence(exec_ctx, tenant_id, fence_scope)

        # Read active pointer
        pointer_stmt = select(METADATA_ACTIVE_POINTERS.c.revision_id).where(
            METADATA_ACTIVE_POINTERS.c.tenant_id == tenant_id,
            METADATA_ACTIVE_POINTERS.c.definition_id == definition_id,
        )
        current_active_rev = (await exec_ctx.execute(pointer_stmt)).scalar_one_or_none()

        preflight_input = PublishPreflightInput(
            definition_id=definition_id,
            expected_draft_generation=def_row["draft_generation"],
            expected_active_revision_id=current_active_rev,
            expected_module_base_generation=fence.module_base_generation,
            expected_schema_ui_generation=fence.schema_ui_generation,
            expected_dependencies_generation=fence.dependencies_generation,
        )

        return PublishPreflightResult(
            valid=True,
            preflight_input=preflight_input,
            current_fence=fence,
        )

    async def publish(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        preflight: PublishPreflightInput,
        published_by: str,
        *,
        comment: str = "",
        fence_scope: str | None = None,
        ctx: Any = None,
    ) -> PublishResult:
        executor = self._get_executor(ctx)
        scope = fence_scope or "global"
        now = datetime.now(UTC)

        try:
            # 1. Acquire fence row FOR UPDATE and verify module/UI/dependency generations
            fence = await acquire_fence_for_publication(
                executor,
                tenant_id,
                scope,
                expected_module_base_generation=preflight.expected_module_base_generation,
                expected_schema_ui_generation=preflight.expected_schema_ui_generation,
                expected_dependencies_generation=preflight.expected_dependencies_generation,
            )

            # 2. Lock definition row FOR UPDATE
            lock_def_stmt = (
                select(METADATA_DEFINITIONS)
                .where(
                    METADATA_DEFINITIONS.c.id == definition_id,
                    METADATA_DEFINITIONS.c.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            def_row = (await executor.execute(lock_def_stmt)).mappings().first()
            if def_row is None:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.POLICY_DENIED,
                    f"Definition '{definition_id}' not found",
                    status_code=404,
                )

            # 3. Check draft generation (detect two-publisher lost-update)
            if def_row["draft_generation"] != preflight.expected_draft_generation:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.STALE_DRAFT,
                    f"Draft generation changed since preflight ({preflight.expected_draft_generation} != {def_row['draft_generation']})",
                    details={
                        "expected": preflight.expected_draft_generation,
                        "actual": def_row["draft_generation"],
                    },
                )

            # 4. Check active revision conflict
            pointer_stmt = (
                select(METADATA_ACTIVE_POINTERS.c.revision_id)
                .where(
                    METADATA_ACTIVE_POINTERS.c.tenant_id == tenant_id,
                    METADATA_ACTIVE_POINTERS.c.definition_id == definition_id,
                )
                .with_for_update()
            )
            current_active_rev = (await executor.execute(pointer_stmt)).scalar_one_or_none()
            if current_active_rev != preflight.expected_active_revision_id:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.ACTIVE_REVISION_CONFLICT,
                    f"Active revision changed since preflight ({preflight.expected_active_revision_id} != {current_active_rev})",
                    details={
                        "expected": str(preflight.expected_active_revision_id),
                        "actual": str(current_active_rev),
                    },
                )

            # 5. Validate draft payload grammar & quota
            if not def_row["draft_payload"]:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    "Definition draft payload is empty",
                )
            payload_model = self.validate_payload(def_row["draft_payload"])
            payload_dict = payload_model.model_dump(mode="json")
            digest = _compute_digest(payload_dict)

            # 6. Determine next revision sequence
            max_seq_stmt = select(METADATA_REVISIONS.c.revision_seq).where(
                METADATA_REVISIONS.c.tenant_id == tenant_id,
                METADATA_REVISIONS.c.definition_id == definition_id,
            ).order_by(desc(METADATA_REVISIONS.c.revision_seq)).limit(1)
            last_seq = (await executor.execute(max_seq_stmt)).scalar_one_or_none() or 0
            new_seq = last_seq + 1

            new_revision_id = uuid4()
            provenance = MetadataRevisionProvenance(
                published_by=published_by,
                published_at=now,
                draft_generation=preflight.expected_draft_generation,
                module_base_generation=fence.module_base_generation,
                schema_ui_generation=fence.schema_ui_generation,
                dependencies_generation=fence.dependencies_generation,
                comment=comment,
            )

            # 7. Write immutable revision
            insert_rev_stmt = insert(METADATA_REVISIONS).values(
                id=new_revision_id,
                tenant_id=tenant_id,
                definition_id=definition_id,
                revision_seq=new_seq,
                schema_version=payload_model.schema_version,
                content_digest=digest,
                payload=payload_dict,
                provenance=provenance.model_dump(mode="json"),
                created_at=now,
            )
            await executor.execute(insert_rev_stmt)

            # 8. Advance fence publication generation
            new_metadata_gen = await advance_fence_publication(
                executor, tenant_id, scope, published_by
            )

            # 9. Atomically upsert active pointer
            upsert_pointer_stmt = (
                insert(METADATA_ACTIVE_POINTERS)
                .values(
                    tenant_id=tenant_id,
                    definition_id=definition_id,
                    revision_id=new_revision_id,
                    active_generation=new_metadata_gen,
                    activated_at=now,
                    activated_by=published_by,
                )
                .on_conflict_do_update(
                    index_elements=[
                        METADATA_ACTIVE_POINTERS.c.tenant_id,
                        METADATA_ACTIVE_POINTERS.c.definition_id,
                    ],
                    set_={
                        "revision_id": new_revision_id,
                        "active_generation": new_metadata_gen,
                        "activated_at": now,
                        "activated_by": published_by,
                    },
                )
            )
            await executor.execute(upsert_pointer_stmt)

            # 10. Update definition status, draft generation, and active revision
            update_def_stmt = (
                METADATA_DEFINITIONS.update()
                .where(
                    METADATA_DEFINITIONS.c.id == definition_id,
                    METADATA_DEFINITIONS.c.tenant_id == tenant_id,
                )
                .values(
                    lifecycle_status=MetadataLifecycleStatus.PUBLISHED.value,
                    draft_generation=def_row["draft_generation"] + 1,
                    active_revision_id=new_revision_id,
                    active_generation=new_metadata_gen,
                    updated_at=now,
                )
            )
            await executor.execute(update_def_stmt)

            rev_record = MetadataRevisionRecord(
                id=new_revision_id,
                tenant_id=tenant_id,
                definition_id=definition_id,
                revision_seq=new_seq,
                schema_version=payload_model.schema_version,
                content_digest=digest,
                payload=payload_dict,
                provenance=provenance,
                created_at=now,
            )

            pointer_record = MetadataActivePointerRecord(
                tenant_id=tenant_id,
                definition_id=definition_id,
                revision_id=new_revision_id,
                active_generation=new_metadata_gen,
                activated_at=now,
                activated_by=published_by,
            )

            # 11. Emit domain event for outbox integration
            if ctx is not None and hasattr(ctx, "emit") and ctx.request.tenant is not None:
                ctx.emit(
                    MetadataRevisionPublished(
                        tenant_id=tenant_id,
                        correlation_id=ctx.request.correlation_id,
                        definition_id=definition_id,
                        revision_id=new_revision_id,
                        revision_seq=new_seq,
                        content_digest=digest,
                        active_generation=new_metadata_gen,
                        published_by=published_by,
                    )
                )

            return PublishResult(
                status=PublishStatus.SUCCESS,
                revision=rev_record,
                active_pointer=pointer_record,
            )

        except MetadataDiagnosticError as err:
            return PublishResult(
                status=PublishStatus(err.diagnostic_code.value),
                diagnostic=err.to_record(),
            )

    # --- Rollback / Reactivation ---

    async def preflight_rollback(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        target_revision_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> RollbackPreflightResult:
        exec_ctx = executor or self._get_executor()

        # Check target revision exists and belongs to this definition
        rev_stmt = select(METADATA_REVISIONS).where(
            METADATA_REVISIONS.c.id == target_revision_id,
            METADATA_REVISIONS.c.definition_id == definition_id,
            METADATA_REVISIONS.c.tenant_id == tenant_id,
        )
        rev_row = (await exec_ctx.execute(rev_stmt)).mappings().first()
        if rev_row is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.REVISION_NOT_FOUND,
                f"Historical revision '{target_revision_id}' not found for definition '{definition_id}'",
                status_code=404,
            )

        pointer_stmt = select(METADATA_ACTIVE_POINTERS.c.revision_id).where(
            METADATA_ACTIVE_POINTERS.c.tenant_id == tenant_id,
            METADATA_ACTIVE_POINTERS.c.definition_id == definition_id,
        )
        current_active = (await exec_ctx.execute(pointer_stmt)).scalar_one_or_none()
        if current_active is None:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.ACTIVE_REVISION_CONFLICT,
                f"Definition '{definition_id}' has no active revision to roll back from",
            )

        fence = await get_or_create_fence(exec_ctx, tenant_id, fence_scope)

        preflight_input = RollbackPreflightInput(
            definition_id=definition_id,
            target_revision_id=target_revision_id,
            expected_active_revision_id=current_active,
            expected_module_base_generation=fence.module_base_generation,
            expected_schema_ui_generation=fence.schema_ui_generation,
            expected_dependencies_generation=fence.dependencies_generation,
        )

        return RollbackPreflightResult(
            valid=True,
            preflight_input=preflight_input,
            current_fence=fence,
        )

    async def rollback(
        self,
        tenant_id: UUID,
        definition_id: UUID,
        target_revision_id: UUID,
        preflight: RollbackPreflightInput,
        reactivated_by: str,
        *,
        comment: str = "",
        fence_scope: str | None = None,
        ctx: Any = None,
    ) -> RollbackResult:
        executor = self._get_executor(ctx)
        scope = fence_scope or "global"
        now = datetime.now(UTC)

        try:
            # 1. Acquire fence row FOR UPDATE
            fence = await acquire_fence_for_publication(
                executor,
                tenant_id,
                scope,
                expected_module_base_generation=preflight.expected_module_base_generation,
                expected_schema_ui_generation=preflight.expected_schema_ui_generation,
                expected_dependencies_generation=preflight.expected_dependencies_generation,
            )

            # 2. Lock definition row FOR UPDATE
            lock_def_stmt = (
                select(METADATA_DEFINITIONS)
                .where(
                    METADATA_DEFINITIONS.c.id == definition_id,
                    METADATA_DEFINITIONS.c.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            def_row = (await executor.execute(lock_def_stmt)).mappings().first()
            if def_row is None:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.POLICY_DENIED,
                    f"Definition '{definition_id}' not found",
                    status_code=404,
                )

            # 3. Check active revision conflict
            pointer_stmt = (
                select(METADATA_ACTIVE_POINTERS.c.revision_id)
                .where(
                    METADATA_ACTIVE_POINTERS.c.tenant_id == tenant_id,
                    METADATA_ACTIVE_POINTERS.c.definition_id == definition_id,
                )
                .with_for_update()
            )
            current_active = (await executor.execute(pointer_stmt)).scalar_one_or_none()
            if current_active != preflight.expected_active_revision_id:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.ACTIVE_REVISION_CONFLICT,
                    f"Active revision changed since rollback preflight ({preflight.expected_active_revision_id} != {current_active})",
                )

            # 4. Verify target revision
            rev_stmt = select(METADATA_REVISIONS).where(
                METADATA_REVISIONS.c.id == target_revision_id,
                METADATA_REVISIONS.c.definition_id == definition_id,
                METADATA_REVISIONS.c.tenant_id == tenant_id,
            )
            rev_row = (await executor.execute(rev_stmt)).mappings().first()
            if rev_row is None:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.REVISION_NOT_FOUND,
                    f"Target revision '{target_revision_id}' not found",
                    status_code=404,
                )

            # 5. Advance fence
            new_metadata_gen = await advance_fence_publication(
                executor, tenant_id, scope, reactivated_by
            )

            # 6. Switch active pointer to target historical revision
            upsert_pointer_stmt = (
                insert(METADATA_ACTIVE_POINTERS)
                .values(
                    tenant_id=tenant_id,
                    definition_id=definition_id,
                    revision_id=target_revision_id,
                    active_generation=new_metadata_gen,
                    activated_at=now,
                    activated_by=reactivated_by,
                )
                .on_conflict_do_update(
                    index_elements=[
                        METADATA_ACTIVE_POINTERS.c.tenant_id,
                        METADATA_ACTIVE_POINTERS.c.definition_id,
                    ],
                    set_={
                        "revision_id": target_revision_id,
                        "active_generation": new_metadata_gen,
                        "activated_at": now,
                        "activated_by": reactivated_by,
                    },
                )
            )
            await executor.execute(upsert_pointer_stmt)

            # 7. Update definition active_revision_id
            update_def_stmt = (
                METADATA_DEFINITIONS.update()
                .where(
                    METADATA_DEFINITIONS.c.id == definition_id,
                    METADATA_DEFINITIONS.c.tenant_id == tenant_id,
                )
                .values(
                    active_revision_id=target_revision_id,
                    active_generation=new_metadata_gen,
                    updated_at=now,
                )
            )
            await executor.execute(update_def_stmt)

            pointer_record = MetadataActivePointerRecord(
                tenant_id=tenant_id,
                definition_id=definition_id,
                revision_id=target_revision_id,
                active_generation=new_metadata_gen,
                activated_at=now,
                activated_by=reactivated_by,
            )

            if ctx is not None and hasattr(ctx, "emit") and ctx.request.tenant is not None:
                ctx.emit(
                    MetadataRevisionReactivated(
                        tenant_id=tenant_id,
                        correlation_id=ctx.request.correlation_id,
                        definition_id=definition_id,
                        revision_id=target_revision_id,
                        revision_seq=rev_row["revision_seq"],
                        active_generation=new_metadata_gen,
                        reactivated_by=reactivated_by,
                    )
                )

            return RollbackResult(
                status=RollbackStatus.SUCCESS,
                active_pointer=pointer_record,
            )

        except MetadataDiagnosticError as err:
            return RollbackResult(
                status=RollbackStatus(err.diagnostic_code.value),
                diagnostic=err.to_record(),
            )

    # --- Publication Fence ---

    async def get_fence_state(
        self,
        tenant_id: UUID,
        fence_scope: str,
        *,
        executor: Any = None,
    ) -> FenceStateRecord:
        exec_ctx = executor or self._get_executor()
        return await get_or_create_fence(exec_ctx, tenant_id, fence_scope)

    # --- Reference Resolution ---

    async def resolve_reference(
        self,
        query: ReferenceResolutionQuery,
        *,
        executor: Any = None,
    ) -> ReferenceResolutionRecord:
        # Cross-tenant references must fail closed
        if query.tenant_id is None:
            return ReferenceResolutionRecord(
                target_record_id=query.target_record_id,
                target_resource_namespace=query.target_resource_namespace,
                state=TargetReferenceState.UNAVAILABLE,
                diagnostic_code=MetadataDiagnosticCode.UNAVAILABLE_TARGET,
                diagnostic_message="Missing tenant context for reference resolution",
            )

        # In Phase 5A, definitions themselves are referenceable platform targets
        if query.target_resource_namespace == "foundation.metadata.definition":
            exec_ctx = executor or self._get_executor()
            stmt = select(METADATA_DEFINITIONS).where(
                METADATA_DEFINITIONS.c.id == query.target_record_id,
                METADATA_DEFINITIONS.c.tenant_id == query.tenant_id,
            )
            row = (await exec_ctx.execute(stmt)).mappings().first()
            if row is None:
                return ReferenceResolutionRecord(
                    target_record_id=query.target_record_id,
                    target_resource_namespace=query.target_resource_namespace,
                    state=TargetReferenceState.UNAVAILABLE,
                    diagnostic_code=MetadataDiagnosticCode.UNAVAILABLE_TARGET,
                    diagnostic_message="Target definition not found or tenant denied",
                )
            if row["lifecycle_status"] in (MetadataLifecycleStatus.RETIRED.value, MetadataLifecycleStatus.ARCHIVED.value):
                return ReferenceResolutionRecord(
                    target_record_id=query.target_record_id,
                    target_resource_namespace=query.target_resource_namespace,
                    state=TargetReferenceState.RETIRED,
                    display_label=row["stable_key"],
                    diagnostic_code=MetadataDiagnosticCode.RETIRED_TARGET,
                    diagnostic_message="Target definition is retired and cannot accept new references",
                )
            return ReferenceResolutionRecord(
                target_record_id=query.target_record_id,
                target_resource_namespace=query.target_resource_namespace,
                state=TargetReferenceState.REFERENCEABLE,
                display_label=row["stable_key"],
            )

        # For external target namespaces, return referenceable or delegate to owner
        return ReferenceResolutionRecord(
            target_record_id=query.target_record_id,
            target_resource_namespace=query.target_resource_namespace,
            state=TargetReferenceState.REFERENCEABLE,
            display_label=str(query.target_record_id),
        )

    async def resolve_bulk_references(
        self,
        query: BulkReferenceResolutionQuery,
        *,
        executor: Any = None,
    ) -> ReferenceResolutionResult:
        if len(query.target_record_ids) > MAX_BULK_REFERENCE_BATCH:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Bulk reference batch size ({len(query.target_record_ids)}) exceeds quota ({MAX_BULK_REFERENCE_BATCH})",
            )

        results: list[ReferenceResolutionRecord] = []
        ref_count = 0
        ret_count = 0
        unav_count = 0

        for target_id in query.target_record_ids:
            single_q = ReferenceResolutionQuery(
                source_resource_namespace=query.source_resource_namespace,
                source_record_id=uuid4(),
                target_resource_namespace=query.target_resource_namespace,
                target_record_id=target_id,
                tenant_id=query.tenant_id,
            )
            res = await self.resolve_reference(single_q, executor=executor)
            results.append(res)
            if res.state == TargetReferenceState.REFERENCEABLE:
                ref_count += 1
            elif res.state == TargetReferenceState.RETIRED:
                ret_count += 1
            else:
                unav_count += 1

        return ReferenceResolutionResult(
            results=results,
            total_count=len(results),
            referenceable_count=ref_count,
            retired_count=ret_count,
            unavailable_count=unav_count,
        )

    def _get_executor(self, ctx: Any = None) -> Any:
        if ctx is not None and hasattr(ctx, "unit_of_work"):
            return ctx.unit_of_work.persistence
        if self._db_executor_factory is not None:
            return self._db_executor_factory()
        raise RuntimeError("No database executor or handling transaction context available")
