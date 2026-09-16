"""SQLAlchemy models owned by the geography foundation."""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

COUNTRIES = Table(
    "countries",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("code", String(2), nullable=False, unique=True),  # ISO 3166-1 alpha-2
    Column("alpha3_code", String(3), nullable=False, unique=True),  # ISO 3166-1 alpha-3
    Column("numeric_code", String(3), nullable=False),
    Column("name", String(200), nullable=False),
    Column("currency_code", String(3), nullable=True),
    Column("phone_prefix", String(10), nullable=True),
    Column("address_format", JSONB(), nullable=False, server_default="{}"),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_geo",
)

SUBDIVISIONS = Table(
    "subdivisions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("country_code", String(2), ForeignKey("platform_geo.countries.code"), nullable=False),
    Column("code", String(10), nullable=False),  # ISO 3166-2 code e.g. US-CA
    Column("name", String(200), nullable=False),
    Column("category", String(50), nullable=False),  # state, province, division, etc.
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("country_code", "code", name="uq_subdivision_country_code"),
    schema="platform_geo",
)

CITIES = Table(
    "cities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("country_code", String(2), ForeignKey("platform_geo.countries.code"), nullable=False),
    Column("subdivision_id", UUID(as_uuid=True), ForeignKey("platform_geo.subdivisions.id"), nullable=True),
    Column("name", String(200), nullable=False),
    Column("postal_code_pattern", String(50), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_geo",
)

ADDRESSES = Table(
    "addresses",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("country_code", String(2), ForeignKey("platform_geo.countries.code"), nullable=False),
    Column("subdivision_code", String(10), nullable=True),
    Column("city", String(200), nullable=False),
    Column("postal_code", String(30), nullable=True),
    Column("street_line1", String(300), nullable=False),
    Column("street_line2", String(300), nullable=True),
    Column("formatted_address", Text(), nullable=False),
    Column("coordinates", JSONB(), nullable=True),
    Column("metadata", JSONB(), nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_geo",
)
