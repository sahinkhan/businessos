"""SQLAlchemy models owned by the party foundation."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

PARTIES = Table(
    "parties",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("party_number", String(50), nullable=False),
    Column("party_type", String(30), nullable=False),  # "person" or "organization"
    Column("display_name", String(255), nullable=False),
    Column("preferred_locale", String(20), nullable=True),
    Column("preferred_timezone", String(50), nullable=True),
    Column("preferred_currency", String(3), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "party_number", name="uq_party_tenant_number"),
    schema="platform_party",
)

PERSON_PROFILES = Table(
    "person_profiles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column(
        "party_id",
        UUID(as_uuid=True),
        ForeignKey("platform_party.parties.id"),
        nullable=False,
        unique=True,
    ),
    Column("first_name", String(100), nullable=False),
    Column("middle_name", String(100), nullable=True),
    Column("last_name", String(100), nullable=False),
    Column("title", String(30), nullable=True),
    Column("date_of_birth", Date(), nullable=True),
    Column("gender", String(30), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_party",
)

ORGANIZATION_PROFILES = Table(
    "organization_profiles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column(
        "party_id",
        UUID(as_uuid=True),
        ForeignKey("platform_party.parties.id"),
        nullable=False,
        unique=True,
    ),
    Column("legal_name", String(255), nullable=False),
    Column("trade_name", String(255), nullable=True),
    Column("tax_identifier", String(100), nullable=True),
    Column("registration_number", String(100), nullable=True),
    Column("website", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_party",
)

PARTY_RELATIONSHIPS = Table(
    "party_relationships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column(
        "from_party_id", UUID(as_uuid=True), ForeignKey("platform_party.parties.id"), nullable=False
    ),
    Column(
        "to_party_id", UUID(as_uuid=True), ForeignKey("platform_party.parties.id"), nullable=False
    ),
    Column("relationship_type", String(50), nullable=False),
    Column("start_date", Date(), nullable=True),
    Column("end_date", Date(), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("notes", Text(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
        name="ck_relationship_dates",
    ),
    schema="platform_party",
)

CONTACT_POINTS = Table(
    "contact_points",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("party_id", UUID(as_uuid=True), ForeignKey("platform_party.parties.id"), nullable=False),
    Column(
        "channel_type", String(30), nullable=False
    ),  # email, phone, mobile, fax, website, social
    Column("value", String(255), nullable=False),
    Column("purpose", String(50), nullable=False, server_default="primary"),
    Column("is_primary", Boolean(), nullable=False, server_default="false"),
    Column("is_verified", Boolean(), nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_party",
)

PARTY_ADDRESS_ASSIGNMENTS = Table(
    "party_address_assignments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("party_id", UUID(as_uuid=True), ForeignKey("platform_party.parties.id"), nullable=False),
    Column(
        "address_id", UUID(as_uuid=True), ForeignKey("platform_geo.addresses.id"), nullable=False
    ),
    Column("purpose", String(50), nullable=False, server_default="billing"),
    Column("is_primary", Boolean(), nullable=False, server_default="false"),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_party",
)

EXTERNAL_IDENTIFIERS = Table(
    "external_identifiers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("party_id", UUID(as_uuid=True), ForeignKey("platform_party.parties.id"), nullable=False),
    Column("provider", String(100), nullable=False),
    Column("identifier_value", String(200), nullable=False),
    Column("is_sensitive", Boolean(), nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "tenant_id", "provider", "identifier_value", name="uq_party_tenant_provider_identifier"
    ),
    schema="platform_party",
)
