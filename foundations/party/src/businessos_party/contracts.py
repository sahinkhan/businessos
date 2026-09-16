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
    model_config = ConfigDict(frozen=True)

    party: PartyRecord
    person_profile: PersonProfileRecord | None = None
    organization_profile: OrganizationProfileRecord | None = None
    contacts: list[ContactPointRecord] = Field(default_factory=list)
    addresses: list[PartyAddressAssignmentRecord] = Field(default_factory=list)
    identifiers: list[ExternalIdentifierRecord] = Field(default_factory=list)
