"""SQLAlchemy models owned by the Currency foundation."""

from sqlalchemy import Boolean, CheckConstraint, Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

CURRENCIES = Table(
    "currencies",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("code", String(3), nullable=False, unique=True),
    Column("numeric_code", String(3), nullable=True, unique=True),
    Column("name", String(120), nullable=False),
    Column("minor_unit", Integer(), nullable=False),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("source", String(80), nullable=False),
    Column("source_version", Integer(), nullable=False),
    CheckConstraint("minor_unit BETWEEN 0 AND 6", name="ck_currency_minor_unit"),
    CheckConstraint("code ~ '^[A-Z]{3}$'", name="ck_currency_alpha_code"),
    CheckConstraint(
        "numeric_code IS NULL OR numeric_code ~ '^[0-9]{3}$'",
        name="ck_currency_numeric_code",
    ),
    CheckConstraint("source_version > 0", name="ck_currency_source_version"),
    schema="platform_currency",
)
