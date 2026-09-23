"""Domain and application contracts for the party foundation."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PartyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_number: str
    party_type: str  # "person" | "organization"
    display_name: str
    preferred_locale: str | None = None
    preferred_timezone: str | None = None
    preferred_currency: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class PersonProfileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_id: UUID
    first_name: str
    middle_name: str | None = None
    last_name: str
    title: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    created_at: datetime


class OrganizationProfileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_id: UUID
    legal_name: str
    trade_name: str | None = None
    tax_identifier: str | None = None
    registration_number: str | None = None
    website: str | None = None
    created_at: datetime


class PartyRelationshipRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    from_party_id: UUID
    to_party_id: UUID
    relationship_type: str
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True
    notes: str | None = None
    created_at: datetime


class ContactPointRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_id: UUID
    channel_type: str
    value: str
    purpose: str
    is_primary: bool = False
    is_verified: bool = False
    created_at: datetime


class PartyAddressAssignmentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_id: UUID
    address_id: UUID
    purpose: str
    is_primary: bool = False
    is_active: bool = True
    created_at: datetime


class ExternalIdentifierRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    party_id: UUID
    provider: str
    identifier_value: str
    is_sensitive: bool = False
    created_at: datetime


class FullPartyRecord(BaseModel):
    """Deprecated v1 complete-or-overflow aggregate response."""

    model_config = ConfigDict(frozen=True)

    party: PartyRecord
    person_profile: PersonProfileRecord | None = None
    organization_profile: OrganizationProfileRecord | None = None
    contacts: list[ContactPointRecord] = Field(default_factory=lambda: list[ContactPointRecord]())
    addresses: list[PartyAddressAssignmentRecord] = Field(
        default_factory=lambda: list[PartyAddressAssignmentRecord]()
    )
    identifiers: list[ExternalIdentifierRecord] = Field(
        default_factory=lambda: list[ExternalIdentifierRecord]()
    )


class FullPartyRecordV2(FullPartyRecord):
    """Complete authorized aggregate under the bounded v2 public contract."""


class DuplicatePartyCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    party_id: UUID
    confidence: str
    reasons: tuple[str, ...]


class DuplicateMatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_party_id: UUID
    candidates: tuple[DuplicatePartyCandidate, ...] = ()


# Public classification for query authors and reviewers. General reads redact these
# values; the sensitive projection requires foundation.party.sensitive.read.
PARTY_SENSITIVE_FIELDS: tuple[str, ...] = (
    "person_profile.date_of_birth",
    "organization_profile.tax_identifier",
    "organization_profile.registration_number",
    "contact.value",
    "external_identifier.identifier_value when is_sensitive",
)


class PartySensitiveReadContract:
    """Versioned marker for sensitive Party projection and lookup queries."""

    version: str = "1.0"


class PartyFullReadV2Contract:
    """Versioned marker for complete-or-overflow Party aggregate queries."""

    version: str = "2.0"


class PartyDuplicateMatchContract:
    """Versioned marker for advisory, tenant-scoped duplicate matching."""

    version: str = "1.0"
