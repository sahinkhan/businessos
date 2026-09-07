"""Public identity, membership and federation contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AuthenticationStrength(StrEnum):
    UNSPECIFIED = "unspecified"
    PASSWORD = "password"
    OIDC = "oidc"
    MFA = "mfa"
    PHISHING_RESISTANT = "phishing_resistant"
    BREAK_GLASS = "break_glass"


class PrincipalIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    principal_id: UUID
    principal_type: str
    authentication_strength: AuthenticationStrength | str
    scopes: tuple[dict[str, str], ...] = ()


class SAMLAssertionValidator(Protocol):
    """Deployment adapter boundary; raw SAML never reaches domain code."""

    async def validate(self, assertion: str) -> PrincipalIdentity: ...


class BreakGlassCredentialValidator(Protocol):
    """Local-only adapter backed by a secret provider, never database plaintext."""

    async def validate(self, credential_reference: str, credential: str) -> bool: ...


class MembershipRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    membership_id: UUID
    tenant_id: UUID
    principal_id: UUID
    principal_type: str
    status: MembershipStatus
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scopes: tuple[dict[str, str], ...] = ()

    def is_effective(self, at: datetime | None = None) -> bool:
        from datetime import UTC

        instant = at or datetime.now(UTC)
        return (
            self.status is MembershipStatus.ACTIVE
            and (self.valid_from is None or self.valid_from <= instant)
            and (self.valid_until is None or self.valid_until >= instant)
        )


class ActiveScopeSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: UUID | None = None
    legal_entity_id: UUID | None = None
    operating_site_id: UUID | None = None
    region_id: UUID | None = None
    warehouse_id: UUID | None = None
    delegation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class IdentityContract:
    version: str = "1.0"
    membership_query: str = "businessos_identity.GetMembership"
    active_scope_contract: str = "businessos_identity.ActiveScopeSelection"
    oidc_resolver: str = "businessos_identity.OIDCContextResolver"
    saml_adapter: str = "businessos_identity.SAMLAssertionValidator"
