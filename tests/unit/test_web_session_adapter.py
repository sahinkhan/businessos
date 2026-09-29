"""Phase 4.5 browser sessions preserve server-side Identity authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_identity.contracts import PrincipalIdentity
from businessos_identity.web_browser import BrowserSessionContextResolver
from businessos_identity.web_sessions import (
    ActiveScope,
    AuthenticatedPrincipal,
    InMemoryAuthorizationTransactionStore,
    InMemoryWebSessionStore,
    WebSessionApplicationService,
    WebSessionConfiguration,
    sanitize_return_path,
    session_cookie,
)

from businessos.sdk import BusinessOSError, RequestContext, RequestIdentity


class _OIDC:
    async def authorization_url(self, **kwargs: object) -> tuple[str, str]:
        return "https://idp.example/authorize", "https://idp.example"

    async def exchange_code(self, **kwargs: object) -> AuthenticatedPrincipal:
        raise AssertionError("Token exchange is not part of this unit proof")


class _Validator:
    def __init__(self) -> None:
        self.allowed = True

    async def validate(self, principal: PrincipalIdentity) -> None:
        if not self.allowed:
            raise BusinessOSError("forbidden", "Membership revoked", status_code=403)


def _service() -> tuple[WebSessionApplicationService, _Validator]:
    validator = _Validator()
    service = WebSessionApplicationService(
        configuration=WebSessionConfiguration(
            installation_id=uuid4(), callback_url="https://app.example/api/v1/auth/callback"
        ),
        sessions=InMemoryWebSessionStore(),
        transactions=InMemoryAuthorizationTransactionStore(),
        oidc=_OIDC(),
        principal_validator=validator,
    )
    return service, validator


def _principal() -> PrincipalIdentity:
    return PrincipalIdentity(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="user",
        authentication_strength="oidc",
    )


@pytest.mark.asyncio
async def test_server_session_revalidates_and_revokes_after_membership_loss() -> None:
    service, validator = _service()
    handle, session = await service.create_session(
        AuthenticatedPrincipal(identity=_principal()), provider_id="default"
    )
    assert await service.get_session(handle) is not None
    assert service.project(session, handle).session_id != handle
    validator.allowed = False
    with pytest.raises(BusinessOSError):
        await service.get_session(handle)
    assert await service.sessions.get(handle) is None


@pytest.mark.asyncio
async def test_scope_rotation_revokes_old_handle_and_csrf_token() -> None:
    service, _ = _service()
    handle, session = await service.create_session(
        AuthenticatedPrincipal(identity=_principal()), provider_id="default"
    )
    new_handle, rotated = await service.rotate_scope(
        handle, ActiveScope(tenant_id=session.principal.tenant_id, company_id=uuid4())
    )
    assert new_handle != handle
    assert rotated.csrf_token != session.csrf_token
    assert await service.sessions.get(handle) is None
    assert (await service.get_session(new_handle)) is not None
    await service.logout(new_handle)
    assert await service.sessions.get(new_handle) is None


@pytest.mark.asyncio
async def test_cookie_resolver_denies_mutation_without_csrf() -> None:
    service, _ = _service()
    handle, session = await service.create_session(
        AuthenticatedPrincipal(identity=_principal()), provider_id="default"
    )

    class _Bearer:
        async def resolve(self, identity: RequestIdentity) -> RequestContext:
            raise AssertionError("Cookie path must not use bearer authority")

    resolver = BrowserSessionContextResolver(
        cast(Any, _Bearer()),
        SimpleNamespace(service=service),  # type: ignore[arg-type]
    )
    identity = RequestIdentity(
        method="POST",
        path="/api/v1/organization/active-scope",
        headers={"cookie": f"__Host-businessos_session={handle}", "host": "app.example"},
        correlation_id="test",
        trace_id="test",
    )
    with pytest.raises(BusinessOSError, match="CSRF"):
        await resolver.resolve(identity)
    allowed = RequestIdentity(
        method=identity.method,
        path=identity.path,
        headers={**identity.headers, "x-csrf-token": session.csrf_token},
        correlation_id=identity.correlation_id,
        trace_id=identity.trace_id,
    )
    assert (await resolver.resolve(allowed)).tenant is not None


def test_session_cookie_and_return_path_safety() -> None:
    cookie = session_cookie("opaque", datetime.now(UTC) + timedelta(minutes=5))
    assert "Secure; HttpOnly; SameSite=Lax" in cookie
    assert sanitize_return_path("/dashboard") == "/dashboard"
    for value in ("https://evil.example", "//evil.example", "/\\evil.example"):
        with pytest.raises(BusinessOSError):
            sanitize_return_path(value)
