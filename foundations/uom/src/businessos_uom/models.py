"""SQLAlchemy models owned by the unit-of-measure foundation."""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

MEASUREMENT_CATEGORIES = Table(
    "measurement_categories",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("description", Text(), nullable=True),
    Column("base_unit_code", String(50), nullable=False),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_meas_cat_tenant_code"),
    schema="platform_uom",
)

UNITS_OF_MEASURE = Table(
    "units_of_measure",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("category_code", String(100), nullable=False),
    Column("code", String(50), nullable=False),
    Column("name", String(200), nullable=False),
    Column("symbol", String(20), nullable=False),
    Column("is_base_unit", Boolean(), nullable=False, server_default="false"),
    Column("conversion_ratio", Numeric(20, 8), nullable=False, server_default="1.0"),
    Column("conversion_offset", Numeric(20, 8), nullable=False, server_default="0.0"),
    Column("precision", Integer(), nullable=False, server_default="2"),
    Column("rounding_mode", String(50), nullable=False, server_default="ROUND_HALF_UP"),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_uom_tenant_code"),
    CheckConstraint("conversion_ratio > 0", name="ck_uom_conversion_ratio_positive"),
    CheckConstraint("precision >= 0", name="ck_uom_precision_nonnegative"),
    schema="platform_uom",
)
