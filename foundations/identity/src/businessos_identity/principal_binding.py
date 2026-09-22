"""Identity-owned, request-bound evidence for an authenticated principal."""

from contextvars import ContextVar
from dataclasses import dataclass

from businessos.sdk import BusinessOSError, DependencyKey, RequestContext

from .contracts import PrincipalIdentity


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipalBinding:
    request: RequestContext
    principal: PrincipalIdentity


AUTHENTICATED_PRINCIPAL = DependencyKey[AuthenticatedPrincipalBinding](
    "businessos.identity.authenticated_principal"
)

_current_binding: ContextVar[AuthenticatedPrincipalBinding | None] = ContextVar(
    "businessos_identity_authenticated_principal", default=None
)


def clear_authenticated_principal() -> None:
    _current_binding.set(None)


def bind_authenticated_principal(request: RequestContext, principal: PrincipalIdentity) -> None:
    tenant = request.tenant
    if (
        tenant is None
        or tenant.tenant_id != principal.tenant_id
        or tenant.principal_id != principal.principal_id
        or principal.principal_type not in {"user", "service_account", "device"}
    ):
        raise BusinessOSError("unauthenticated", "Trusted principal mismatch", status_code=401)
    _current_binding.set(AuthenticatedPrincipalBinding(request, principal))


def current_authenticated_principal() -> AuthenticatedPrincipalBinding:
    binding = _current_binding.get()
    if binding is None:
        raise BusinessOSError("unauthenticated", "Trusted principal required", status_code=401)
    return binding
