"""Diagnostic codes and exception definitions for the Metadata foundation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from businessos.sdk import BusinessOSError


class MetadataDiagnosticCode(StrEnum):
    STALE_DRAFT = "stale_draft"
    ACTIVE_REVISION_CONFLICT = "active_revision_conflict"
    MODULE_BASE_GENERATION_CHANGED = "module_base_generation_changed"
    SCHEMA_UI_GENERATION_CHANGED = "schema_ui_generation_changed"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    UNAVAILABLE_TARGET = "unavailable_target"
    RETIRED_TARGET = "retired_target"
    UNSUPPORTED_CROSS_OWNER_DELETION = "unsupported_cross_owner_deletion"
    QUOTA_EXCEEDED = "quota_exceeded"
    VALIDATION_FAILED = "validation_failed"
    POLICY_DENIED = "policy_denied"
    REVISION_NOT_FOUND = "revision_not_found"
    INCOMPATIBLE_REVISION = "incompatible_revision"


class MetadataDiagnosticRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: MetadataDiagnosticCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MetadataDiagnosticError(BusinessOSError):
    """Domain error representing a typed, diagnosable metadata rejection."""

    def __init__(
        self,
        code: MetadataDiagnosticCode | str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(str(code), message, status_code=status_code)
        self.diagnostic_code = (
            code if isinstance(code, MetadataDiagnosticCode) else MetadataDiagnosticCode(code)
        )
        self.diagnostic_details = details or {}

    def to_record(self) -> MetadataDiagnosticRecord:
        return MetadataDiagnosticRecord(
            code=self.diagnostic_code,
            message=str(self),
            details=self.diagnostic_details,
        )
