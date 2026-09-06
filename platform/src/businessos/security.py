"""Identity, authorization, secret and audit boundaries for later foundation modules."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError


class PrincipalType(StrEnum):
    USER = "user"
    SERVICE_ACCOUNT = "service_account"
    DEVICE = "device"


@dataclass(frozen=True, slots=True)
class Principal:
    id: UUID
    type: PrincipalType
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    method: str
    path: str
    headers: Mapping[str, str]
    correlation_id: str
    trace_id: str


class TrustedContextResolver(Protocol):
    async def resolve(self, identity: RequestIdentity) -> RequestContext: ...


class AnonymousContextResolver:
    """Preserve correlation without trusting client-supplied tenant identity."""

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        return RequestContext(
            correlation_id=identity.correlation_id,
            trace_id=identity.trace_id,
            tenant=None,
        )


class IdentityProvider(Protocol):
    async def authenticate(self, credential: str) -> Principal: ...


class OIDCProvider(IdentityProvider, Protocol):
    @property
    def issuer(self) -> str: ...


class PolicyEvaluator(Protocol):
    async def is_allowed(
        self, principal_id: UUID, tenant: TenantContext, permission: str
    ) -> bool: ...


class Authorizer:
    def __init__(self, evaluator: PolicyEvaluator) -> None:
        self._evaluator = evaluator

    async def require(self, context: RequestContext, permission: str) -> None:
        if context.tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        if not await self._evaluator.is_allowed(
            context.tenant.principal_id, context.tenant, permission
        ):
            raise BusinessOSError("forbidden", "Permission denied", status_code=403)


class DenyAllPolicyEvaluator:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return False


class SecretProvider(Protocol):
    async def get_secret(self, reference: str) -> str: ...


class SecurityAuditHook(Protocol):
    async def record(
        self,
        *,
        context: RequestContext,
        action: str,
        resource: str,
        decision: str,
    ) -> None: ...
