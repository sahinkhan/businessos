"""Identity, authorization, secret and audit boundaries for later foundation modules."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.persistence import UnitOfWorkFactory
from businessos.persistence.contracts import TransactionalPersistence


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


class ContextResolverFactory(Protocol):
    def __call__(
        self, installation_id: UUID, unit_of_work_factory: UnitOfWorkFactory
    ) -> TrustedContextResolver: ...


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


@runtime_checkable
class FencedPolicyEvaluator(PolicyEvaluator, Protocol):
    """Backend Policy authority, not sequential client-visible permission checks.

    Implementations must evaluate the entire set against one current snapshot,
    fence all applicable revocation writers until exit (including outer commit),
    and reject stale/expired Identity, scope and Policy evidence. The persistence
    is the framework-owned operation; it must never be committed by an evaluator.
    Unrelated tenants/principals must not share a global process mutex.
    """

    def permission_fence(
        self,
        context: RequestContext,
        permissions: frozenset[str],
        persistence: TransactionalPersistence,
    ) -> AbstractAsyncContextManager[None]: ...


class Authorizer:
    def __init__(self, evaluator: PolicyEvaluator) -> None:
        self._evaluator = evaluator

    @property
    def supports_permission_fence(self) -> bool:
        """Composition capability check; provider synchronization needs certification."""
        return isinstance(self._evaluator, FencedPolicyEvaluator)

    async def require(self, context: RequestContext, permission: str) -> None:
        if context.tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        if not await self._evaluator.is_allowed(
            context.tenant.principal_id, context.tenant, permission
        ):
            raise BusinessOSError("forbidden", "Permission denied", status_code=403)

    @asynccontextmanager
    async def permission_fence(
        self,
        context: RequestContext,
        permissions: frozenset[str],
        persistence: TransactionalPersistence,
    ) -> AsyncGenerator[None]:
        if context.tenant is None or not isinstance(self._evaluator, FencedPolicyEvaluator):
            raise BusinessOSError(
                "authority_fence_required", "Coherent Policy authority required", status_code=403
            )
        async with self._evaluator.permission_fence(context, permissions, persistence):
            yield


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
