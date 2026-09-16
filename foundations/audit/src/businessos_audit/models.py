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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

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
    Column("status", String(30), nullable=False, server_default="success"),
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
) -> str:
    raw = f"{previous_checksum}|{tenant_id}|{occurred_at.isoformat()}|{actor_id}|{action}|{resource_type}|{resource_id or ''}|{status}"
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
    status: str = "success"
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
    tampered_ids: list[UUID] = Field(default_factory=list)
