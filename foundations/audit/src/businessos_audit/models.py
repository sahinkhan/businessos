"""SQLAlchemy and Pydantic boundary models for the audit foundation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

AUDIT_LOGS = Table(
    "audit_logs",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actor_id", String(100), nullable=False),
    Column("actor_type", String(50), nullable=False, server_default="user"),
    Column("action", String(100), nullable=False),
    Column("resource_type", String(100), nullable=False),
    Column("resource_id", String(255), nullable=True),
    Column("scope_type", String(50), nullable=True),
    Column("scope_id", PG_UUID(as_uuid=True), nullable=True),
    Column("before_state", JSONB, nullable=True),
    Column("after_state", JSONB, nullable=True),
    Column("correlation_id", String(100), nullable=True),
    Column("client_ip", String(50), nullable=True),
    Column("user_agent", String(255), nullable=True),
    Column("decision_metadata", JSONB, nullable=True),
    Column("trace_id", String(100), nullable=True),
    Column("status", String(30), nullable=False, server_default="success"),
    Column("previous_checksum", String(64), nullable=False, server_default=""),
    Column("integrity_version", String(10), nullable=False, server_default="2"),
    Column("provenance_v3", JSONB, nullable=True),
    Column("evidence_v3", JSONB, nullable=True),
    Column("source_event_id", PG_UUID(as_uuid=True), nullable=True),
    Column("projection_kind", String(50), nullable=True),
    Column("checksum", String(64), nullable=False),
    Index("ix_audit_tenant_occurred", "tenant_id", "occurred_at"),
    Index("ix_audit_tenant_resource", "tenant_id", "resource_type", "resource_id"),
    Index("ix_audit_tenant_correlation", "tenant_id", "correlation_id"),
    schema="platform_audit",
)


def compute_audit_checksum(
    tenant_id: UUID,
    occurred_at: datetime,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    status: str,
    previous_checksum: str = "",
    *,
    actor_type: str = "user",
    scope_type: str | None = None,
    scope_id: UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    decision_metadata: dict[str, Any] | None = None,
    integrity_version: str = "1",
) -> str:
    if integrity_version == "1":
        raw = (
            f"{previous_checksum}|{tenant_id}|{occurred_at.isoformat()}|{actor_id}|"
            f"{action}|{resource_type}|{resource_id or ''}|{status}"
        )
    else:
        payload = {
            "action": action,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "after_state": after_state,
            "before_state": before_state,
            "correlation_id": correlation_id,
            "decision_metadata": decision_metadata,
            "occurred_at": occurred_at.isoformat(),
            "previous_checksum": previous_checksum,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "scope_id": str(scope_id) if scope_id else None,
            "scope_type": scope_type,
            "status": status,
            "tenant_id": str(tenant_id),
            "trace_id": trace_id,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_audit_checksum_v3(envelope: dict[str, Any]) -> str:
    """A separate canonical encoding; historical version 1/2 bytes are unchanged."""
    payload = {"integrity_version": "3", **envelope}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    occurred_at: datetime
    actor_id: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None = None
    scope_type: str | None = None
    scope_id: UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    correlation_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    decision_metadata: dict[str, Any] | None = None
    trace_id: str | None = None
    status: str = "success"
    previous_checksum: str = ""
    integrity_version: str = "2"
    provenance_v3: dict[str, Any] | None = None
    evidence_v3: dict[str, Any] | None = None
    source_event_id: UUID | None = None
    projection_kind: str | None = None
    checksum: str


class RecordAuditEvent(BaseModel):
    tenant_id: UUID
    actor_id: str = Field(min_length=1, max_length=100)
    actor_type: str = Field(default="user", max_length=50)
    action: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=255)
    scope_type: str | None = Field(default=None, max_length=50)
    scope_id: UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    correlation_id: str | None = Field(default=None, max_length=100)
    client_ip: str | None = Field(default=None, max_length=50)
    user_agent: str | None = Field(default=None, max_length=255)
    decision_metadata: dict[str, Any] | None = None
    status: str = Field(default="success", max_length=30)


class AuditVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_records: int
    is_valid: bool
    tampered_ids: list[UUID] = Field(default_factory=lambda: list[UUID]())
