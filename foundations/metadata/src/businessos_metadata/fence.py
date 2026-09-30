"""PostgreSQL-compatible publication and module-activation serialization fence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from .diagnostics import MetadataDiagnosticCode, MetadataDiagnosticError
from .models import METADATA_PUBLICATION_FENCES


class FenceStateRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    fence_scope: str
    metadata_generation: int
    module_base_generation: int
    schema_ui_generation: int
    dependencies_generation: int
    last_fenced_at: datetime
    last_fenced_by: str


async def get_or_create_fence(
    executor: Any,
    tenant_id: UUID,
    fence_scope: str,
) -> FenceStateRecord:
    """Read the current fence state, creating initial generation 1 if not yet established."""
    stmt = (
        insert(METADATA_PUBLICATION_FENCES)
        .values(
            tenant_id=tenant_id,
            fence_scope=fence_scope,
            metadata_generation=1,
            module_base_generation=1,
            schema_ui_generation=1,
            dependencies_generation=1,
            last_fenced_at=datetime.now(UTC),
            last_fenced_by="system",
        )
        .on_conflict_do_nothing()
    )
    await executor.execute(stmt)

    select_stmt = select(METADATA_PUBLICATION_FENCES).where(
        METADATA_PUBLICATION_FENCES.c.tenant_id == tenant_id,
        METADATA_PUBLICATION_FENCES.c.fence_scope == fence_scope,
    )
    result = await executor.execute(select_stmt)
    row = result.mappings().first()
    if row is None:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.INCOMPATIBLE_DEPENDENCY,
            f"Failed to initialize publication fence for scope {fence_scope}",
        )
    return FenceStateRecord(
        tenant_id=row["tenant_id"],
        fence_scope=row["fence_scope"],
        metadata_generation=row["metadata_generation"],
        module_base_generation=row["module_base_generation"],
        schema_ui_generation=row["schema_ui_generation"],
        dependencies_generation=row["dependencies_generation"],
        last_fenced_at=row["last_fenced_at"],
        last_fenced_by=row["last_fenced_by"],
    )


async def acquire_fence_for_publication(
    executor: Any,
    tenant_id: UUID,
    fence_scope: str,
    *,
    expected_module_base_generation: int,
    expected_schema_ui_generation: int,
    expected_dependencies_generation: int,
) -> FenceStateRecord:
    """Lock the fence row FOR UPDATE and verify that base, UI, and dependency generations have not changed."""
    # Ensure row exists first
    await get_or_create_fence(executor, tenant_id, fence_scope)

    lock_stmt = (
        select(METADATA_PUBLICATION_FENCES)
        .where(
            METADATA_PUBLICATION_FENCES.c.tenant_id == tenant_id,
            METADATA_PUBLICATION_FENCES.c.fence_scope == fence_scope,
        )
        .with_for_update()
    )
    result = await executor.execute(lock_stmt)
    row = result.mappings().first()
    if row is None:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.INCOMPATIBLE_DEPENDENCY,
            f"Fence row missing during lock for scope {fence_scope}",
        )

    # Validate generation invariants
    if row["module_base_generation"] != expected_module_base_generation:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.MODULE_BASE_GENERATION_CHANGED,
            f"Module base generation changed from preflight ({expected_module_base_generation} != {row['module_base_generation']})",
            details={
                "expected": expected_module_base_generation,
                "authoritative": row["module_base_generation"],
            },
        )

    if row["schema_ui_generation"] != expected_schema_ui_generation:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.SCHEMA_UI_GENERATION_CHANGED,
            f"UI schema generation changed from preflight ({expected_schema_ui_generation} != {row['schema_ui_generation']})",
            details={
                "expected": expected_schema_ui_generation,
                "authoritative": row["schema_ui_generation"],
            },
        )

    if row["dependencies_generation"] != expected_dependencies_generation:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.INCOMPATIBLE_DEPENDENCY,
            f"Dependency generation changed from preflight ({expected_dependencies_generation} != {row['dependencies_generation']})",
            details={
                "expected": expected_dependencies_generation,
                "authoritative": row["dependencies_generation"],
            },
        )

    return FenceStateRecord(
        tenant_id=row["tenant_id"],
        fence_scope=row["fence_scope"],
        metadata_generation=row["metadata_generation"],
        module_base_generation=row["module_base_generation"],
        schema_ui_generation=row["schema_ui_generation"],
        dependencies_generation=row["dependencies_generation"],
        last_fenced_at=row["last_fenced_at"],
        last_fenced_by=row["last_fenced_by"],
    )


async def advance_fence_publication(
    executor: Any,
    tenant_id: UUID,
    fence_scope: str,
    published_by: str,
) -> int:
    """Atomically increment the metadata_generation on successful publication or reactivation."""
    stmt = (
        METADATA_PUBLICATION_FENCES.update()
        .where(
            METADATA_PUBLICATION_FENCES.c.tenant_id == tenant_id,
            METADATA_PUBLICATION_FENCES.c.fence_scope == fence_scope,
        )
        .values(
            metadata_generation=METADATA_PUBLICATION_FENCES.c.metadata_generation + 1,
            last_fenced_at=datetime.now(UTC),
            last_fenced_by=published_by,
        )
        .returning(METADATA_PUBLICATION_FENCES.c.metadata_generation)
    )
    result = await executor.execute(stmt)
    new_gen = result.scalar_one()
    return int(new_gen)


async def acquire_fence_for_module_activation(
    executor: Any,
    tenant_id: UUID,
    fence_scope: str,
    *,
    expected_metadata_generation: int,
) -> FenceStateRecord:
    """Module install/activation/upgrade fence verification.

    Locks the fence FOR UPDATE and verifies metadata has not advanced since preflight.
    """
    await get_or_create_fence(executor, tenant_id, fence_scope)

    lock_stmt = (
        select(METADATA_PUBLICATION_FENCES)
        .where(
            METADATA_PUBLICATION_FENCES.c.tenant_id == tenant_id,
            METADATA_PUBLICATION_FENCES.c.fence_scope == fence_scope,
        )
        .with_for_update()
    )
    result = await executor.execute(lock_stmt)
    row = result.mappings().first()
    if row is None:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.INCOMPATIBLE_DEPENDENCY,
            f"Fence row missing during lock for scope {fence_scope}",
        )

    if row["metadata_generation"] != expected_metadata_generation:
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.ACTIVE_REVISION_CONFLICT,
            f"Metadata generation changed during module activation preflight ({expected_metadata_generation} != {row['metadata_generation']})",
            details={
                "expected": expected_metadata_generation,
                "authoritative": row["metadata_generation"],
            },
        )

    return FenceStateRecord(
        tenant_id=row["tenant_id"],
        fence_scope=row["fence_scope"],
        metadata_generation=row["metadata_generation"],
        module_base_generation=row["module_base_generation"],
        schema_ui_generation=row["schema_ui_generation"],
        dependencies_generation=row["dependencies_generation"],
        last_fenced_at=row["last_fenced_at"],
        last_fenced_by=row["last_fenced_by"],
    )


async def advance_fence_module_activation(
    executor: Any,
    tenant_id: UUID,
    fence_scope: str,
    activated_by: str,
    *,
    new_module_base_generation: int | None = None,
) -> int:
    """Atomically update module_base_generation on module activation/upgrade commit."""
    values: dict[str, Any] = {
        "last_fenced_at": datetime.now(UTC),
        "last_fenced_by": activated_by,
    }
    if new_module_base_generation is not None:
        values["module_base_generation"] = new_module_base_generation
    else:
        values["module_base_generation"] = METADATA_PUBLICATION_FENCES.c.module_base_generation + 1

    stmt = (
        METADATA_PUBLICATION_FENCES.update()
        .where(
            METADATA_PUBLICATION_FENCES.c.tenant_id == tenant_id,
            METADATA_PUBLICATION_FENCES.c.fence_scope == fence_scope,
        )
        .values(**values)
        .returning(METADATA_PUBLICATION_FENCES.c.module_base_generation)
    )
    result = await executor.execute(stmt)
    new_gen = result.scalar_one()
    return int(new_gen)
