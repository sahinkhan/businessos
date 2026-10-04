"""Metadata-owned UI overlay persistence; no customer DDL or business values."""

from sqlalchemy import JSON, BigInteger, Column, DateTime, String, Table, Uuid

from .models import SCHEMA, metadata

UI_OVERLAYS = Table(
    "ui_overlays",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("view_id", Uuid(as_uuid=True), nullable=False),
    Column("scope_kind", String(20), nullable=False),
    Column("scope_id", Uuid(as_uuid=True), nullable=False),
    Column("lifecycle", String(20), nullable=False),
    Column("draft_generation", BigInteger, nullable=False),
    Column("draft_document", JSON, nullable=False),
    Column("draft_compatibility_digest", String(64), nullable=False),
    Column("active_generation", BigInteger, nullable=False),
    Column("active_revision_id", Uuid(as_uuid=True)),
    Column("created_by", Uuid(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True)),
    schema=SCHEMA,
)
UI_REVISIONS = Table(
    "ui_overlay_revisions",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
    Column("overlay_id", Uuid(as_uuid=True), nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column("document", JSON, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("compatibility_digest", String(64), nullable=False),
    Column("published_by", Uuid(as_uuid=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    schema=SCHEMA,
)
