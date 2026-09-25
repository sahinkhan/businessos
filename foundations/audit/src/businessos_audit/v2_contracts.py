"""Audit V2 evidence is caller supplied; actor and time are authority supplied."""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from businessos.sdk import Command, DependencyKey, HandlingContext

from .models import AuditRecord

_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "credential",
    "token",
    "api_key",
    "private_key",
    "authorization",
    "cookie",
)


def _validate_evidence_json(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or any(
                part in key.lower() for part in _SENSITIVE_KEY_PARTS
            ):
                raise ValueError("Audit evidence contains a sensitive or invalid key")
            _validate_evidence_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_evidence_json(item)
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float) and math.isfinite(value):
        return
    else:
        raise ValueError("Audit evidence must contain only finite JSON values")


class AuditEvidenceV2(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=255)
    status: str = Field(default="success", min_length=1, max_length=30)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_details(self) -> AuditEvidenceV2:
        _validate_evidence_json(self.details)
        if len(json.dumps(self.details, sort_keys=True, ensure_ascii=False).encode("utf-8")) > 8192:
            raise ValueError("Audit evidence exceeds 8192 bytes")
        return self


class RecordAuditLogV2(Command):
    """Manual principal-authorized write; no actor/tenant/time input."""

    evidence: AuditEvidenceV2


class AuditAppenderV2(Protocol):
    async def append(self, evidence: AuditEvidenceV2, ctx: HandlingContext) -> AuditRecord: ...


AUDIT_APPENDER_V2 = DependencyKey[AuditAppenderV2](
    "foundation.audit.appender.v2", required_owner="foundation.audit"
)
