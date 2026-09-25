"""Public identity, membership and federation contracts."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict

from businessos.sdk import (
    DependencyKey,
    HandlerTransaction,
    TransactionalPersistence,
    WorkloadAdmissionDenied,
)

type PrincipalType = Literal["user", "service_account", "device"]


class InvalidWorkloadCredential(WorkloadAdmissionDenied):
    """Non-secret authentication failure; never classify as a poison event."""


@dataclass(frozen=True, slots=True)
class VerifiedWorkloadIdentity:
    installation_id: UUID
    workload_id: UUID
    principal_type: Literal["service_account"]
    purpose: str
    process_class: str
    credential_reference: str
    credential_generation: int
    verification_method: str
    verification_reference: UUID
    valid_from: datetime
    valid_until: datetime
    _issuer: object = field(repr=False, compare=False)


@dataclass(slots=True)
class _BindingLease:
    active: bool = True


@dataclass(frozen=True, slots=True)
class WorkloadIdentityFacts:
    """Visible provenance without the authority's reusable admission proof."""

    installation_id: UUID
    workload_id: UUID
    principal_type: Literal["service_account"]
    purpose: str
    process_class: str
    credential_reference: str
    credential_generation: int
    verification_method: str
    verification_reference: UUID


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class TenantExecutionBinding:
    workload: WorkloadIdentityFacts
    tenant_id: UUID
    source_event_id: UUID
    subscriber: str
    attempt_id: UUID
    purpose: Literal["event-delivery"]
    transaction_id: int
    valid_from: datetime
    valid_until: datetime
    _task_id: int = field(repr=False, compare=False)
    _lease: _BindingLease = field(repr=False, compare=False)

    def assert_active(self, transaction: HandlerTransaction) -> None:
        import asyncio

        task = asyncio.current_task()
        if (
            self not in _issued_execution_bindings
            or not self._lease.active
            or id(transaction) != self.transaction_id
            or task is None
            or id(task) != self._task_id
            or datetime.now(self.valid_until.tzinfo) >= self.valid_until
        ):
            raise InvalidWorkloadCredential("Workload execution binding is not active")


_issued_execution_bindings: WeakKeyDictionary[TenantExecutionBinding, object] = WeakKeyDictionary()


def _issue_tenant_execution_binding(binding: TenantExecutionBinding) -> None:  # pyright: ignore[reportUnusedFunction]
    _issued_execution_bindings[binding] = binding._lease  # pyright: ignore[reportPrivateUsage]


class WorkloadCredentialVerifier(Protocol):
    async def verify(
        self,
        persistence: TransactionalPersistence,
        *,
        installation_id: UUID,
        workload_id: UUID,
        process_class: str,
        purpose: str,
        credential_reference: str,
        credential: bytes,
    ) -> VerifiedWorkloadIdentity: ...


class WorkloadExecutionAuthority(WorkloadCredentialVerifier, Protocol):
    def bind(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkloadIdentity,
        tenant_id: UUID,
        source_event_id: UUID,
        subscriber: str,
        attempt_id: UUID,
        transaction: HandlerTransaction,
    ) -> AbstractAsyncContextManager[TenantExecutionBinding]: ...

    def operation(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkloadIdentity,
        purpose: str,
    ) -> AbstractAsyncContextManager[None]: ...


WORKLOAD_EXECUTION_AUTHORITY = DependencyKey[WorkloadExecutionAuthority](
    "businessos.identity.workload_execution_authority.v1"
)


@dataclass(frozen=True, slots=True, order=True)
class PrincipalReference:
    principal_type: PrincipalType
    principal_id: UUID


class MembershipAuthority(Protocol):
    """Validate and lock typed memberships in the caller's transaction."""

    async def lock_current(
        self,
        persistence: TransactionalPersistence,
        tenant_id: UUID,
        principal: PrincipalReference,
    ) -> tuple["MembershipRecord", datetime]:
        """Lock first, then choose and validate one current UTC decision instant."""
        ...

    async def lock_many(
        self,
        persistence: TransactionalPersistence,
        tenant_id: UUID,
        principals: tuple[PrincipalReference, ...],
        evaluated_at: datetime,
        valid_from: datetime,
        valid_until: datetime,
    ) -> tuple["MembershipRecord", ...]: ...


MEMBERSHIP_AUTHORITY = DependencyKey[MembershipAuthority](
    "businessos.identity.membership_authority"
)


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


class AuthenticationSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: UUID
    tenant_id: UUID
    principal_id: UUID
    principal_type: str
    authentication_strength: AuthenticationStrength | str
    started_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def is_active(self, at: datetime | None = None) -> bool:
        from datetime import UTC

        instant = at or datetime.now(UTC)
        return self.revoked_at is None and self.started_at <= instant < self.expires_at


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
            and (self.valid_until is None or instant < self.valid_until)
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
    version: str = "1.3"
    membership_query: str = "businessos_identity.GetMembership"
    active_scope_contract: str = "businessos_identity.ActiveScopeSelection"
    oidc_resolver: str = "businessos_identity.OIDCContextResolver"
    saml_adapter: str = "businessos_identity.SAMLAssertionValidator"
    session_start_command: str = "businessos_identity.StartAuthenticationSession"
    session_revoke_command: str = "businessos_identity.RevokeAuthenticationSession"
    session_query: str = "businessos_identity.GetAuthenticationSession"
    session_validation_query: str = "businessos_identity.ValidateAuthenticationSession"
    workload_execution_authority: str = "businessos.identity.workload_execution_authority.v1"
