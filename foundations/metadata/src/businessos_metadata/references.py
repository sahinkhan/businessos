"""Reference resolution contracts, bounded bulk queries, and cross-owner deletion invariants."""

from __future__ import annotations

from enum import StrEnum
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .diagnostics import MetadataDiagnosticCode, MetadataDiagnosticError
from .grammar import MAX_BULK_REFERENCE_BATCH


class TargetReferenceState(StrEnum):
    REFERENCEABLE = "referenceable"
    RETIRED = "retired"
    UNAVAILABLE = "unavailable"
    DIAGNOSTICALLY_BROKEN = "diagnostically_broken"


class ReferenceResolutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_record_id: UUID
    target_resource_namespace: str
    state: TargetReferenceState
    display_label: str | None = None
    diagnostic_code: MetadataDiagnosticCode | None = None
    diagnostic_message: str | None = None


class ReferenceResolutionQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_resource_namespace: str = Field(min_length=1, max_length=100)
    source_record_id: UUID
    target_resource_namespace: str = Field(min_length=1, max_length=100)
    target_record_id: UUID
    tenant_id: UUID


class BulkReferenceResolutionQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_resource_namespace: str = Field(min_length=1, max_length=100)
    target_resource_namespace: str = Field(min_length=1, max_length=100)
    target_record_ids: list[UUID] = Field(min_length=1)
    tenant_id: UUID

    @model_validator(mode="after")
    def validate_bounded_bulk(self) -> BulkReferenceResolutionQuery:
        if len(self.target_record_ids) > MAX_BULK_REFERENCE_BATCH:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Bulk reference query exceeds maximum batch limit ({len(self.target_record_ids)} > {MAX_BULK_REFERENCE_BATCH})",
                details={
                    "limit": MAX_BULK_REFERENCE_BATCH,
                    "actual": len(self.target_record_ids),
                },
            )
        return self


class ReferenceResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    results: list[ReferenceResolutionRecord]
    total_count: int
    referenceable_count: int
    retired_count: int
    unavailable_count: int


def validate_cross_owner_deletion(
    source_owner: str,
    target_owner: str,
    on_delete: str,
) -> None:
    """Enforce ADR-023 cross-owner reference deletion invariant.

    For same-owner source and target, that owner may certify restrict, nullify, or cascade
    under its own transaction.
    For cross-owner references, Phase 5 promises NO generic synchronous restrict, nullify, or cascade
    on target retirement or deletion: source owner owns its reference value, target owner owns target lifecycle,
    and neither Metadata nor target owner directly mutates another owner's source row.
    """
    normalized = on_delete.strip().lower()
    if source_owner != target_owner and normalized in ("cascade", "nullify", "restrict", "set_null"):
        raise MetadataDiagnosticError(
            MetadataDiagnosticCode.UNSUPPORTED_CROSS_OWNER_DELETION,
            f"Unsupported cross-owner deletion action '{on_delete}' between '{source_owner}' and '{target_owner}'. "
            "Cross-owner references do not support synchronous restrict, nullify, or cascade side effects.",
            details={
                "source_owner": source_owner,
                "target_owner": target_owner,
                "requested_action": on_delete,
            },
        )
