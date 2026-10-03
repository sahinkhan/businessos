"""Private Metadata-owned SQLAlchemy Core table definitions."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
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
    UniqueConstraint("tenant_id", "id", name="uq_metadata_definition_tenant_id"),
    Index(
        "uq_metadata_definition_identity",
        "tenant_id",
        "resource_namespace",
        "kind",
        unique=True,
        postgresql_where=Column("kind") != "custom_entity",
    ),
    CheckConstraint(
        "kind IN ('field_set','reference_set','custom_entity')", name="ck_metadata_kind"
    ),
    CheckConstraint(
        "(kind = 'custom_entity') = (resource_namespace = 'foundation.metadata.custom_entity') "
        "AND (kind <> 'custom_entity' OR (owner_module_id = 'foundation.metadata' "
        "AND owner_contract_version = '1'))",
        name="ck_metadata_custom_entity_identity",
    ),
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
    UniqueConstraint("tenant_id", "definition_id", "id", "digest", name="uq_metadata_revision_pin"),
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

CUSTOM_ENTITIES = Table(
    "custom_entities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("definition_id", UUID(as_uuid=True), nullable=False),
    Column("revision_id", UUID(as_uuid=True), nullable=False),
    Column("revision_digest", String(64), nullable=False),
    Column("lifecycle", String(20), nullable=False),
    Column("scope_kind", String(30), nullable=False),
    Column("scope_id", UUID(as_uuid=True), nullable=False),
    Column("value_version", BigInteger(), nullable=False),
    Column("value_document", JSONB(), nullable=False),
    Column("created_by", UUID(as_uuid=True), nullable=False),
    Column("updated_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["tenant_id", "definition_id", "revision_id", "revision_digest"],
        [
            f"{SCHEMA}.revisions.tenant_id",
            f"{SCHEMA}.revisions.definition_id",
            f"{SCHEMA}.revisions.id",
            f"{SCHEMA}.revisions.digest",
        ],
        name="fk_metadata_custom_entity_pin",
        ondelete="RESTRICT",
    ),
    CheckConstraint("value_version > 0", name="ck_metadata_custom_entity_version"),
    CheckConstraint("revision_digest ~ '^[a-f0-9]{64}$'", name="ck_metadata_custom_entity_digest"),
    CheckConstraint(
        "lifecycle IN ('current','archived')", name="ck_metadata_custom_entity_lifecycle"
    ),
    CheckConstraint(
        "(lifecycle = 'archived') = (archived_at IS NOT NULL)",
        name="ck_metadata_custom_entity_archive",
    ),
    CheckConstraint(
        "scope_kind IN ('tenant','company','enterprise_group','legal_entity','business_unit',"
        "'division','department','team','region','operating_site','warehouse','cost_center',"
        "'profit_center','project') AND (scope_kind <> 'tenant' OR scope_id = tenant_id)",
        name="ck_metadata_custom_entity_scope",
    ),
    CheckConstraint(
        "jsonb_typeof(value_document) = 'object' AND octet_length(value_document::text) <= 1048576",
        name="ck_metadata_custom_entity_document",
    ),
    Index(
        "ix_metadata_custom_entity_type_scope",
        "tenant_id",
        "definition_id",
        "scope_kind",
        "scope_id",
        "id",
    ),
    Index("ix_metadata_custom_entity_lifecycle", "tenant_id", "definition_id", "lifecycle", "id"),
    schema=SCHEMA,
)
