"""SQLAlchemy and Pydantic boundary models for persistent metadata definitions and revisions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

SCHEMA = "platform_metadata"
metadata = MetaData()

METADATA_DEFINITIONS = Table(
    "metadata_definitions",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False, index=True),
    Column("owner_namespace", String(100), nullable=False),
    Column("definition_kind", String(50), nullable=False),
    Column("stable_key", String(100), nullable=False),
    Column("lifecycle_status", String(50), nullable=False, server_default="draft"),
    Column("draft_generation", Integer, nullable=False, server_default="1"),
    Column("draft_payload", JSONB, nullable=True),
    Column("active_revision_id", PG_UUID(as_uuid=True), nullable=True),
    Column("active_generation", Integer, nullable=False, server_default="0"),
    Column("created_by", String(100), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "tenant_id",
        "owner_namespace",
        "definition_kind",
        "stable_key",
        name="uq_metadata_definition_key",
    ),
    schema=SCHEMA,
)

METADATA_REVISIONS = Table(
    "metadata_revisions",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False, index=True),
    Column("definition_id", PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.metadata_definitions.id", ondelete="RESTRICT"), nullable=False),
    Column("revision_seq", Integer, nullable=False),
    Column("schema_version", String(20), nullable=False, server_default="1"),
    Column("content_digest", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("provenance", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "definition_id", "revision_seq", name="uq_metadata_revision_seq"),
    UniqueConstraint("tenant_id", "definition_id", "content_digest", name="uq_metadata_revision_digest"),
    schema=SCHEMA,
)

METADATA_ACTIVE_POINTERS = Table(
    "metadata_active_pointers",
    metadata,
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("definition_id", PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.metadata_definitions.id", ondelete="RESTRICT"), nullable=False),
    Column("revision_id", PG_UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.metadata_revisions.id", ondelete="RESTRICT"), nullable=False),
    Column("active_generation", Integer, nullable=False),
    Column("activated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("activated_by", String(100), nullable=False),
    PrimaryKeyConstraint("tenant_id", "definition_id", name="pk_metadata_active_pointers"),
    schema=SCHEMA,
)

METADATA_PUBLICATION_FENCES = Table(
    "metadata_publication_fences",
    metadata,
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("fence_scope", String(100), nullable=False),
    Column("metadata_generation", Integer, nullable=False, server_default="1"),
    Column("module_base_generation", Integer, nullable=False, server_default="1"),
    Column("schema_ui_generation", Integer, nullable=False, server_default="1"),
    Column("dependencies_generation", Integer, nullable=False, server_default="1"),
    Column("last_fenced_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_fenced_by", String(100), nullable=False, server_default="system"),
    PrimaryKeyConstraint("tenant_id", "fence_scope", name="pk_metadata_publication_fences"),
    schema=SCHEMA,
)


class MetadataDefinitionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    tenant_id: UUID
    owner_namespace: str
    definition_kind: str
    stable_key: str
    lifecycle_status: str
    draft_generation: int
    draft_payload: dict[str, object] | None = None
    active_revision_id: UUID | None = None
    active_generation: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class MetadataRevisionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    tenant_id: UUID
    definition_id: UUID
    revision_seq: int
    schema_version: str
    content_digest: str
    payload: dict[str, object]
    provenance: dict[str, object]
    created_at: datetime


class MetadataActivePointerModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    tenant_id: UUID
    definition_id: UUID
    revision_id: UUID
    active_generation: int
    activated_at: datetime
    activated_by: str


class MetadataPublicationFenceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    tenant_id: UUID
    fence_scope: str
    metadata_generation: int
    module_base_generation: int
    schema_ui_generation: int
    dependencies_generation: int
    last_fenced_at: datetime
    last_fenced_by: str
