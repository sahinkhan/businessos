"""SQLAlchemy models owned by the reference data foundation."""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

REFERENCE_SETS = Table(
    "reference_sets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("description", Text(), nullable=True),
    Column("owning_module", String(100), nullable=False),
    Column("is_extensible", Boolean(), nullable=False, server_default="true"),
    Column("is_system", Boolean(), nullable=False, server_default="false"),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_ref_set_tenant_code"),
    schema="platform_ref",
)

REFERENCE_VALUES = Table(
    "reference_values",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("set_code", String(100), nullable=False),
    Column("code", String(100), nullable=False),
    Column("label_key", String(200), nullable=False),
    Column("default_label", String(200), nullable=False),
    Column("description", Text(), nullable=True),
    Column("external_id", String(200), nullable=True),
    Column("sort_order", Integer(), nullable=False, server_default="0"),
    Column("seed_version", Integer(), nullable=False, server_default="1"),
    Column("effective_from", DateTime(timezone=True), nullable=True),
    Column("effective_until", DateTime(timezone=True), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("properties", JSONB(), nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "set_code", "code", name="uq_ref_value_tenant_set_code"),
    CheckConstraint(
        "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
        name="ck_ref_value_effective_dates",
    ),
    schema="platform_ref",
)

NUMBER_SEQUENCES = Table(
    "number_sequences",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("prefix", String(30), nullable=False, server_default=""),
    Column("suffix", String(30), nullable=False, server_default=""),
    Column("next_value", BigInteger(), nullable=False, server_default="1"),
    Column("step", Integer(), nullable=False, server_default="1"),
    Column("padding", Integer(), nullable=False, server_default="6"),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_number_seq_tenant_code"),
    CheckConstraint("next_value >= 1", name="ck_number_seq_next_value_positive"),
    schema="platform_ref",
)
