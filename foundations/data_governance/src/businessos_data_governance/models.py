"""SQLAlchemy and Pydantic boundary models for data governance, retention, and privacy."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

DATA_CLASSIFICATIONS = Table(
    "data_classifications",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("sensitivity_level", Integer(), nullable=False),
    Column("description", Text(), nullable=False, server_default=""),
    schema="platform_gov",
)

RETENTION_POLICIES = Table(
    "retention_policies",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column(
        "classification_code",
        String(50),
        ForeignKey("platform_gov.data_classifications.code", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("retention_period_days", Integer(), nullable=False),
    Column(
        "action_on_expiry", String(50), nullable=False, server_default="archive"
    ),  # "archive", "anonymize", "purge"
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_retention_tenant_code"),
    schema="platform_gov",
)

LEGAL_HOLDS = Table(
    "legal_holds",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("reason", Text(), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column("entity_id", String(255), nullable=True),
    Column("placed_by", String(100), nullable=False),
    Column("placed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("released_by", String(100), nullable=True),
    Column("released_at", DateTime(timezone=True), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    UniqueConstraint("tenant_id", "code", name="uq_legal_holds_tenant_code"),
    schema="platform_gov",
)

CONSENT_RECORDS = Table(
    "consent_records",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("subject_id", PG_UUID(as_uuid=True), nullable=False),
    Column("purpose_code", String(100), nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="true"),
    schema="platform_gov",
)

SENSITIVE_FIELD_TAGS = Table(
    "sensitive_field_tags",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column("field_name", String(100), nullable=False),
    Column(
        "classification_code",
        String(50),
        ForeignKey("platform_gov.data_classifications.code", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("is_masked_by_default", Boolean(), nullable=False, server_default="false"),
    Column("description", Text(), nullable=False, server_default=""),
    UniqueConstraint(
        "tenant_id", "entity_type", "field_name", name="uq_field_tag_tenant_entity_field"
    ),
    schema="platform_gov",
)


class ExpiryAction(StrEnum):
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"
    PURGE = "purge"


class DataClassificationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    sensitivity_level: int
    description: str = ""


class RetentionPolicyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    entity_type: str
    classification_code: str
    retention_period_days: int
    action_on_expiry: ExpiryAction
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LegalHoldRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    reason: str
    entity_type: str
    entity_id: str | None = None
    placed_by: str
    placed_at: datetime
    released_by: str | None = None
    released_at: datetime | None = None
    is_active: bool


class ConsentRecordModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    subject_id: UUID
    purpose_code: str
    granted_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    is_active: bool


class SensitiveFieldTagRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    entity_type: str
    field_name: str
    classification_code: str
    is_masked_by_default: bool
    description: str = ""


class PurgeEligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    can_purge: bool
    reason: str
    active_holds: list[str] = Field(default_factory=list)


class ConsentVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_consent: bool
    reason: str
