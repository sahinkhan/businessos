"""Party, contacts, and relationship foundation module registration and handlers."""

import json
from datetime import date, datetime
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, or_, select, update

from businessos.sdk import (
    BusinessOSError,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import (
    ContactPointRecord,
    ExternalIdentifierRecord,
    FullPartyRecord,
    OrganizationProfileRecord,
    PartyAddressAssignmentRecord,
    PartyRecord,
    PartyRelationshipRecord,
    PersonProfileRecord,
)
from .models import (
    CONTACT_POINTS,
    EXTERNAL_IDENTIFIERS,
    ORGANIZATION_PROFILES,
    PARTIES,
    PARTY_ADDRESS_ASSIGNMENTS,
    PARTY_RELATIONSHIPS,
    PERSON_PROFILES,
)


class CreatePersonParty(Command):
    tenant_id: UUID
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=30)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)
    preferred_locale: str | None = Field(default=None, max_length=20)
    preferred_timezone: str | None = Field(default=None, max_length=50)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)


class CreateOrganizationParty(Command):
    tenant_id: UUID
    legal_name: str = Field(min_length=1, max_length=255)
    trade_name: str | None = Field(default=None, max_length=255)
    tax_identifier: str | None = Field(default=None, max_length=100)
    registration_number: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=255)
    preferred_locale: str | None = Field(default=None, max_length=20)
    preferred_timezone: str | None = Field(default=None, max_length=50)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)


class UpdateParty(Command):
    tenant_id: UUID
    party_id: UUID
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    preferred_locale: str | None = Field(default=None, max_length=20)
    preferred_timezone: str | None = Field(default=None, max_length=50)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None


class AddPartyRelationship(Command):
    tenant_id: UUID
    from_party_id: UUID
    to_party_id: UUID
    relationship_type: str = Field(min_length=1, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None


class AddContactPoint(Command):
    tenant_id: UUID
    party_id: UUID
    channel_type: str = Field(min_length=1, max_length=30)
    value: str = Field(min_length=1, max_length=255)
    purpose: str = Field(default="primary", max_length=50)
    is_primary: bool = False
    is_verified: bool = False


class AssignPartyAddress(Command):
    tenant_id: UUID
    party_id: UUID
    address_id: UUID
    purpose: str = Field(default="billing", max_length=50)
    is_primary: bool = False


class AddExternalIdentifier(Command):
    tenant_id: UUID
    party_id: UUID
    provider: str = Field(min_length=1, max_length=100)
    identifier_value: str = Field(min_length=1, max_length=200)
    is_sensitive: bool = False


class GetParty(Query):
    tenant_id: UUID
    party_id: UUID


class GetFullParty(Query):
    tenant_id: UUID
    party_id: UUID


class SearchParties(Query):
    tenant_id: UUID
    query: str = Field(min_length=1, max_length=100)
    party_type: str | None = None


class ResolvePartyByExternalId(Query):
    tenant_id: UUID
    provider: str
    identifier_value: str


class ListPartyRelationships(Query):
    tenant_id: UUID
    party_id: UUID


class PartyCreated(DomainEvent):
    event_type: ClassVar[str] = "party.created.v1"
    party_id: UUID
    party_number: str
    party_type: str
    display_name: str


class PartyUpdated(DomainEvent):
    event_type: ClassVar[str] = "party.updated.v1"
    party_id: UUID
    display_name: str


class PartyRelationshipCreated(DomainEvent):
    event_type: ClassVar[str] = "party.relationship.created.v1"
    relationship_id: UUID
    from_party_id: UUID
    to_party_id: UUID
    relationship_type: str


class PartyModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_party").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.party.read", description="Read party and profile records"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.party.manage", description="Manage party and profile records"
            )
        )

        registration.command(
            CreatePersonParty, self._create_person, permission="foundation.party.manage"
        )
        registration.command(
            CreateOrganizationParty, self._create_organization, permission="foundation.party.manage"
        )
        registration.command(UpdateParty, self._update_party, permission="foundation.party.manage")
        registration.command(
            AddPartyRelationship, self._add_relationship, permission="foundation.party.manage"
        )
        registration.command(
            AddContactPoint, self._add_contact, permission="foundation.party.manage"
        )
        registration.command(
            AssignPartyAddress, self._assign_address, permission="foundation.party.manage"
        )
        registration.command(
            AddExternalIdentifier, self._add_identifier, permission="foundation.party.manage"
        )

        registration.query(GetParty, self._get_party, permission="foundation.party.read")
        registration.query(GetFullParty, self._get_full_party, permission="foundation.party.read")
        registration.query(SearchParties, self._search_parties, permission="foundation.party.read")
        registration.query(
            ResolvePartyByExternalId,
            self._resolve_by_external_id,
            permission="foundation.party.read",
        )
        registration.query(
            ListPartyRelationships, self._list_relationships, permission="foundation.party.read"
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _create_person(
        self, command: CreatePersonParty, context: HandlingContext
    ) -> PartyRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        party_id = uuid4()
        party_num = f"PRT-{party_id.hex[:8].upper()}"
        display_name = f"{command.first_name} {command.last_name}"

        res = await context.unit_of_work.persistence.execute(
            insert(PARTIES)
            .values(
                id=party_id,
                tenant_id=tenant.tenant_id,
                party_number=party_num,
                party_type="person",
                display_name=display_name,
                preferred_locale=command.preferred_locale,
                preferred_timezone=command.preferred_timezone,
                preferred_currency=command.preferred_currency,
                is_active=True,
            )
            .returning(PARTIES.c.created_at, PARTIES.c.updated_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()
        updated_at = row[1] if row else datetime.now()

        profile_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(PERSON_PROFILES).values(
                id=profile_id,
                tenant_id=tenant.tenant_id,
                party_id=party_id,
                first_name=command.first_name,
                middle_name=command.middle_name,
                last_name=command.last_name,
                title=command.title,
                date_of_birth=command.date_of_birth,
                gender=command.gender,
            )
        )

        context.emit(
            PartyCreated(
                party_id=party_id,
                party_number=party_num,
                party_type="person",
                display_name=display_name,
            )
        )
        return PartyRecord(
            id=party_id,
            tenant_id=tenant.tenant_id,
            party_number=party_num,
            party_type="person",
            display_name=display_name,
            preferred_locale=command.preferred_locale,
            preferred_timezone=command.preferred_timezone,
            preferred_currency=command.preferred_currency,
            is_active=True,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _create_organization(
        self, command: CreateOrganizationParty, context: HandlingContext
    ) -> PartyRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        party_id = uuid4()
        party_num = f"PRT-{party_id.hex[:8].upper()}"
        display_name = command.legal_name

        res = await context.unit_of_work.persistence.execute(
            insert(PARTIES)
            .values(
                id=party_id,
                tenant_id=tenant.tenant_id,
                party_number=party_num,
                party_type="organization",
                display_name=display_name,
                preferred_locale=command.preferred_locale,
                preferred_timezone=command.preferred_timezone,
                preferred_currency=command.preferred_currency,
                is_active=True,
            )
            .returning(PARTIES.c.created_at, PARTIES.c.updated_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()
        updated_at = row[1] if row else datetime.now()

        profile_id = uuid4()
        await context.unit_of_work.persistence.execute(
            insert(ORGANIZATION_PROFILES).values(
                id=profile_id,
                tenant_id=tenant.tenant_id,
                party_id=party_id,
                legal_name=command.legal_name,
                trade_name=command.trade_name,
                tax_identifier=command.tax_identifier,
                registration_number=command.registration_number,
                website=command.website,
            )
        )

        context.emit(
            PartyCreated(
                party_id=party_id,
                party_number=party_num,
                party_type="organization",
                display_name=display_name,
            )
        )
        return PartyRecord(
            id=party_id,
            tenant_id=tenant.tenant_id,
            party_number=party_num,
            party_type="organization",
            display_name=display_name,
            preferred_locale=command.preferred_locale,
            preferred_timezone=command.preferred_timezone,
            preferred_currency=command.preferred_currency,
            is_active=True,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _update_party(self, command: UpdateParty, context: HandlingContext) -> PartyRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        values: dict[str, object] = {"updated_at": datetime.now()}
        if command.display_name is not None:
            values["display_name"] = command.display_name
        if command.preferred_locale is not None:
            values["preferred_locale"] = command.preferred_locale
        if command.preferred_timezone is not None:
            values["preferred_timezone"] = command.preferred_timezone
        if command.preferred_currency is not None:
            values["preferred_currency"] = command.preferred_currency
        if command.is_active is not None:
            values["is_active"] = command.is_active

        await context.unit_of_work.persistence.execute(
            update(PARTIES)
            .where(
                PARTIES.c.tenant_id == tenant.tenant_id,
                PARTIES.c.id == command.party_id,
            )
            .values(**values)
        )

        party = await self._get_party(
            GetParty(tenant_id=tenant.tenant_id, party_id=command.party_id), context
        )
        if not party:
            raise BusinessOSError("party not found", status_code=404)

        context.emit(PartyUpdated(party_id=party.id, display_name=party.display_name))
        return party

    async def _add_relationship(
        self, command: AddPartyRelationship, context: HandlingContext
    ) -> PartyRelationshipRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        # Verify both parties belong to active tenant
        from_p = await self._get_party(
            GetParty(tenant_id=tenant.tenant_id, party_id=command.from_party_id), context
        )
        to_p = await self._get_party(
            GetParty(tenant_id=tenant.tenant_id, party_id=command.to_party_id), context
        )
        if not from_p or not to_p:
            raise BusinessOSError("both parties must exist in the tenant boundary", status_code=404)

        rel_id = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(PARTY_RELATIONSHIPS)
            .values(
                id=rel_id,
                tenant_id=tenant.tenant_id,
                from_party_id=command.from_party_id,
                to_party_id=command.to_party_id,
                relationship_type=command.relationship_type,
                start_date=command.start_date,
                end_date=command.end_date,
                notes=command.notes,
                is_active=True,
            )
            .returning(PARTY_RELATIONSHIPS.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()

        context.emit(
            PartyRelationshipCreated(
                relationship_id=rel_id,
                from_party_id=command.from_party_id,
                to_party_id=command.to_party_id,
                relationship_type=command.relationship_type,
            )
        )
        return PartyRelationshipRecord(
            id=rel_id,
            tenant_id=tenant.tenant_id,
            from_party_id=command.from_party_id,
            to_party_id=command.to_party_id,
            relationship_type=command.relationship_type,
            start_date=command.start_date,
            end_date=command.end_date,
            notes=command.notes,
            is_active=True,
            created_at=created_at,
        )

    async def _add_contact(
        self, command: AddContactPoint, context: HandlingContext
    ) -> ContactPointRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        cid = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(CONTACT_POINTS)
            .values(
                id=cid,
                tenant_id=tenant.tenant_id,
                party_id=command.party_id,
                channel_type=command.channel_type,
                value=command.value,
                purpose=command.purpose,
                is_primary=command.is_primary,
                is_verified=command.is_verified,
            )
            .returning(CONTACT_POINTS.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()
        return ContactPointRecord(
            id=cid,
            tenant_id=tenant.tenant_id,
            party_id=command.party_id,
            channel_type=command.channel_type,
            value=command.value,
            purpose=command.purpose,
            is_primary=command.is_primary,
            is_verified=command.is_verified,
            created_at=created_at,
        )

    async def _assign_address(
        self, command: AssignPartyAddress, context: HandlingContext
    ) -> PartyAddressAssignmentRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        aid = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(PARTY_ADDRESS_ASSIGNMENTS)
            .values(
                id=aid,
                tenant_id=tenant.tenant_id,
                party_id=command.party_id,
                address_id=command.address_id,
                purpose=command.purpose,
                is_primary=command.is_primary,
                is_active=True,
            )
            .returning(PARTY_ADDRESS_ASSIGNMENTS.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()
        return PartyAddressAssignmentRecord(
            id=aid,
            tenant_id=tenant.tenant_id,
            party_id=command.party_id,
            address_id=command.address_id,
            purpose=command.purpose,
            is_primary=command.is_primary,
            is_active=True,
            created_at=created_at,
        )

    async def _add_identifier(
        self, command: AddExternalIdentifier, context: HandlingContext
    ) -> ExternalIdentifierRecord:
        tenant = _require_tenant(context.request, command.tenant_id)
        eid = uuid4()
        res = await context.unit_of_work.persistence.execute(
            insert(EXTERNAL_IDENTIFIERS)
            .values(
                id=eid,
                tenant_id=tenant.tenant_id,
                party_id=command.party_id,
                provider=command.provider,
                identifier_value=command.identifier_value,
                is_sensitive=command.is_sensitive,
            )
            .returning(EXTERNAL_IDENTIFIERS.c.created_at)
        )
        row = res.first()
        created_at = row[0] if row else datetime.now()
        return ExternalIdentifierRecord(
            id=eid,
            tenant_id=tenant.tenant_id,
            party_id=command.party_id,
            provider=command.provider,
            identifier_value=command.identifier_value,
            is_sensitive=command.is_sensitive,
            created_at=created_at,
        )

    async def _get_party(self, query: GetParty, context: HandlingContext) -> PartyRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(PARTIES).where(
            PARTIES.c.tenant_id == tenant.tenant_id,
            PARTIES.c.id == query.party_id,
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return PartyRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            party_number=row.party_number,
            party_type=row.party_type,
            display_name=row.display_name,
            preferred_locale=row.preferred_locale,
            preferred_timezone=row.preferred_timezone,
            preferred_currency=row.preferred_currency,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _get_full_party(
        self, query: GetFullParty, context: HandlingContext
    ) -> FullPartyRecord | None:
        party = await self._get_party(
            GetParty(tenant_id=query.tenant_id, party_id=query.party_id), context
        )
        if not party:
            return None

        tenant = _require_tenant(context.request, query.tenant_id)

        # Profiles
        person_prof = None
        if party.party_type == "person":
            p_stmt = select(PERSON_PROFILES).where(
                PERSON_PROFILES.c.tenant_id == tenant.tenant_id,
                PERSON_PROFILES.c.party_id == party.id,
            )
            p_row = (await context.unit_of_work.persistence.execute(p_stmt)).first()
            if p_row:
                person_prof = PersonProfileRecord(
                    id=p_row.id,
                    tenant_id=p_row.tenant_id,
                    party_id=p_row.party_id,
                    first_name=p_row.first_name,
                    middle_name=p_row.middle_name,
                    last_name=p_row.last_name,
                    title=p_row.title,
                    date_of_birth=p_row.date_of_birth,
                    gender=p_row.gender,
                    created_at=p_row.created_at,
                )

        org_prof = None
        if party.party_type == "organization":
            o_stmt = select(ORGANIZATION_PROFILES).where(
                ORGANIZATION_PROFILES.c.tenant_id == tenant.tenant_id,
                ORGANIZATION_PROFILES.c.party_id == party.id,
            )
            o_row = (await context.unit_of_work.persistence.execute(o_stmt)).first()
            if o_row:
                org_prof = OrganizationProfileRecord(
                    id=o_row.id,
                    tenant_id=o_row.tenant_id,
                    party_id=o_row.party_id,
                    legal_name=o_row.legal_name,
                    trade_name=o_row.trade_name,
                    tax_identifier=o_row.tax_identifier,
                    registration_number=o_row.registration_number,
                    website=o_row.website,
                    created_at=o_row.created_at,
                )

        # Contacts
        c_stmt = select(CONTACT_POINTS).where(
            CONTACT_POINTS.c.tenant_id == tenant.tenant_id,
            CONTACT_POINTS.c.party_id == party.id,
        )
        c_rows = (await context.unit_of_work.persistence.execute(c_stmt)).fetchall()
        contacts = [
            ContactPointRecord(
                id=r.id,
                tenant_id=r.tenant_id,
                party_id=r.party_id,
                channel_type=r.channel_type,
                value=r.value,
                purpose=r.purpose,
                is_primary=r.is_primary,
                is_verified=r.is_verified,
                created_at=r.created_at,
            )
            for r in c_rows
        ]

        # Addresses
        a_stmt = select(PARTY_ADDRESS_ASSIGNMENTS).where(
            PARTY_ADDRESS_ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
            PARTY_ADDRESS_ASSIGNMENTS.c.party_id == party.id,
        )
        a_rows = (await context.unit_of_work.persistence.execute(a_stmt)).fetchall()
        addresses = [
            PartyAddressAssignmentRecord(
                id=r.id,
                tenant_id=r.tenant_id,
                party_id=r.party_id,
                address_id=r.address_id,
                purpose=r.purpose,
                is_primary=r.is_primary,
                is_active=r.is_active,
                created_at=r.created_at,
            )
            for r in a_rows
        ]

        # Identifiers
        i_stmt = select(EXTERNAL_IDENTIFIERS).where(
            EXTERNAL_IDENTIFIERS.c.tenant_id == tenant.tenant_id,
            EXTERNAL_IDENTIFIERS.c.party_id == party.id,
        )
        i_rows = (await context.unit_of_work.persistence.execute(i_stmt)).fetchall()
        identifiers = [
            ExternalIdentifierRecord(
                id=r.id,
                tenant_id=r.tenant_id,
                party_id=r.party_id,
                provider=r.provider,
                identifier_value=r.identifier_value,
                is_sensitive=r.is_sensitive,
                created_at=r.created_at,
            )
            for r in i_rows
        ]

        return FullPartyRecord(
            party=party,
            person_profile=person_prof,
            organization_profile=org_prof,
            contacts=contacts,
            addresses=addresses,
            identifiers=identifiers,
        )

    async def _search_parties(
        self, query: SearchParties, context: HandlingContext
    ) -> list[PartyRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(PARTIES).where(
            PARTIES.c.tenant_id == tenant.tenant_id,
            or_(
                PARTIES.c.display_name.ilike(f"%{query.query}%"),
                PARTIES.c.party_number.ilike(f"%{query.query}%"),
            ),
        )
        if query.party_type:
            stmt = stmt.where(PARTIES.c.party_type == query.party_type)
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            PartyRecord(
                id=r.id,
                tenant_id=r.tenant_id,
                party_number=r.party_number,
                party_type=r.party_type,
                display_name=r.display_name,
                preferred_locale=r.preferred_locale,
                preferred_timezone=r.preferred_timezone,
                preferred_currency=r.preferred_currency,
                is_active=r.is_active,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in result.fetchall()
        ]

    async def _resolve_by_external_id(
        self, query: ResolvePartyByExternalId, context: HandlingContext
    ) -> PartyRecord | None:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = (
            select(PARTIES)
            .join(EXTERNAL_IDENTIFIERS, EXTERNAL_IDENTIFIERS.c.party_id == PARTIES.c.id)
            .where(
                EXTERNAL_IDENTIFIERS.c.tenant_id == tenant.tenant_id,
                EXTERNAL_IDENTIFIERS.c.provider == query.provider,
                EXTERNAL_IDENTIFIERS.c.identifier_value == query.identifier_value,
            )
        )
        row = (await context.unit_of_work.persistence.execute(stmt)).first()
        if not row:
            return None
        return PartyRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            party_number=row.party_number,
            party_type=row.party_type,
            display_name=row.display_name,
            preferred_locale=row.preferred_locale,
            preferred_timezone=row.preferred_timezone,
            preferred_currency=row.preferred_currency,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _list_relationships(
        self, query: ListPartyRelationships, context: HandlingContext
    ) -> list[PartyRelationshipRecord]:
        tenant = _require_tenant(context.request, query.tenant_id)
        stmt = select(PARTY_RELATIONSHIPS).where(
            PARTY_RELATIONSHIPS.c.tenant_id == tenant.tenant_id,
            or_(
                PARTY_RELATIONSHIPS.c.from_party_id == query.party_id,
                PARTY_RELATIONSHIPS.c.to_party_id == query.party_id,
            ),
        )
        result = await context.unit_of_work.persistence.execute(stmt)
        return [
            PartyRelationshipRecord(
                id=r.id,
                tenant_id=r.tenant_id,
                from_party_id=r.from_party_id,
                to_party_id=r.to_party_id,
                relationship_type=r.relationship_type,
                start_date=r.start_date,
                end_date=r.end_date,
                notes=r.notes,
                is_active=r.is_active,
                created_at=r.created_at,
            )
            for r in result.fetchall()
        ]


def _require_tenant(request: RequestContext | None, target_tenant_id: UUID) -> TenantContext:
    if request is None or request.tenant is None:
        raise BusinessOSError("tenant context is required", status_code=400)
    if request.tenant.tenant_id != target_tenant_id:
        raise BusinessOSError("target tenant does not match active boundary", status_code=403)
    return request.tenant
