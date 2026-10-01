"""Private Metadata-owned SQLAlchemy Core table definitions."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()
SCHEMA = "platform_metadata"

MODULE_FENCE = Table(
    "module_fence",
    metadata,
    Column("module_id", String(150), primary_key=True),
    Column("artifact_identity", String(200), nullable=False),
    Column("generation", BigInteger(), nullable=False),
    Column("active_bindings", BigInteger(), nullable=False, server_default="0"),
    CheckConstraint("generation > 0", name="ck_metadata_module_generation"),
    CheckConstraint("active_bindings >= 0", name="ck_metadata_active_bindings"),
    schema=SCHEMA,
)

CONTRACT_FENCE = Table(
    "contract_fence",
    metadata,
    Column("id", Integer(), primary_key=True),
    Column("schema_generation", BigInteger(), nullable=False),
    Column("ui_generation", BigInteger(), nullable=False),
    schema=SCHEMA,
)

DEFINITIONS = Table(
    "definitions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("owner_module_id", String(150), nullable=False),
    Column("resource_namespace", String(200), nullable=False),
    Column("owner_contract_version", String(30), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("lifecycle", String(20), nullable=False),
    Column("draft_generation", BigInteger(), nullable=False, server_default="1"),
    Column("draft_snapshot", JSONB(), nullable=False),
    Column("active_revision_id", UUID(as_uuid=True)),
    Column("active_generation", BigInteger(), nullable=False, server_default="0"),
    Column("created_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "tenant_id", "resource_namespace", "kind", name="uq_metadata_definition_identity"
    ),
    UniqueConstraint("tenant_id", "id", name="uq_metadata_definition_tenant_id"),
    CheckConstraint("kind IN ('field_set','reference_set')", name="ck_metadata_kind"),
    CheckConstraint("lifecycle IN ('draft','published','retired')", name="ck_metadata_lifecycle"),
    schema=SCHEMA,
)

REVISIONS = Table(
    "revisions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("definition_id", UUID(as_uuid=True), nullable=False),
    Column("sequence", BigInteger(), nullable=False),
    Column("snapshot", JSONB(), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("schema_generation", BigInteger(), nullable=False),
    Column("ui_generation", BigInteger(), nullable=False),
    Column("published_by", UUID(as_uuid=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("provenance", String(200), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "definition_id"],
        [f"{SCHEMA}.definitions.tenant_id", f"{SCHEMA}.definitions.id"],
        ondelete="RESTRICT",
        name="fk_metadata_revision_definition_tenant",
    ),
    UniqueConstraint(
        "tenant_id", "definition_id", "sequence", name="uq_metadata_revision_sequence"
    ),
    UniqueConstraint("tenant_id", "definition_id", "id", name="uq_metadata_revision_active_target"),
    UniqueConstraint("tenant_id", "id", name="uq_metadata_revision_tenant_id"),
    schema=SCHEMA,
)

REVISION_MODULE_BINDINGS = Table(
    "revision_module_bindings",
    metadata,
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("revision_id", UUID(as_uuid=True), nullable=False),
    Column("module_id", String(150), nullable=False),
    Column("artifact_identity", String(200), nullable=False),
    Column("generation", BigInteger(), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "revision_id"],
        [f"{SCHEMA}.revisions.tenant_id", f"{SCHEMA}.revisions.id"],
        ondelete="RESTRICT",
        name="fk_metadata_binding_revision_tenant",
    ),
    ForeignKeyConstraint(
        ["module_id"],
        [f"{SCHEMA}.module_fence.module_id"],
        ondelete="RESTRICT",
        name="fk_metadata_binding_module",
    ),
    PrimaryKeyConstraint("tenant_id", "revision_id", "module_id"),
    schema=SCHEMA,
)
