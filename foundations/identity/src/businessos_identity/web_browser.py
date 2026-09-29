"""Optional production browser composition around the existing Identity authority."""

from __future__ import annotations

import asyncio
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

import httpx
from businessos_tenant import DatabaseTenantAccessValidator
from redis.asyncio import from_url  # pyright: ignore[reportUnknownVariableType]

from businessos.sdk import BusinessOSError, RequestContext, RequestIdentity, UnitOfWorkFactory

from .oidc import OIDCContextResolver
from .principal_binding import bind_authenticated_principal
from .web_sessions import (
    SESSION_COOKIE,
    DatabasePrincipalSessionValidator,
    OIDCAuthorizationCodeAdapter,
    RedisAuthorizationTransactionStore,
    RedisWebSessionStore,
    WebSessionApplicationService,
    WebSessionConfiguration,
    cookie_value,
)


@dataclass(frozen=True, slots=True)
class BrowserOIDCSettings:
    redis_url: str
    callback_url: str
    authorization_url: str
    token_url: str
    issuer: str
    client_id: str
    client_secret_file: str | None = None

    @classmethod
    def from_environment(cls) -> BrowserOIDCSettings | None:
        names = (
            "BOS_WEB_SESSION_REDIS_URL",
            "BOS_WEB_OIDC_CALLBACK_URL",
            "BOS_WEB_OIDC_AUTHORIZATION_URL",
            "BOS_WEB_OIDC_TOKEN_URL",
            "BOS_WEB_OIDC_ISSUER",
            "BOS_WEB_OIDC_CLIENT_ID",
        )
        values = tuple(os.environ.get(name) for name in names)
        if not any(values):
            return None
        if not all(values):
            raise ValueError("Browser OIDC configuration is incomplete")
        complete = cast(tuple[str, str, str, str, str, str], values)
        return cls(*complete, os.environ.get("BOS_WEB_OIDC_CLIENT_SECRET_FILE"))

    def __post_init__(self) -> None:
        if not self.redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("Browser session store requires Redis")
        if not all(
            value.startswith("https://")
            for value in (
                self.callback_url,
                self.authorization_url,
                self.token_url,
                self.issuer,
            )
        ):
            raise ValueError("Browser OIDC endpoints must use HTTPS")
        if not self.client_id.strip():
            raise ValueError("OIDC client ID is required")


class HttpOIDCAuthorizationClient:
    def __init__(self, settings: BrowserOIDCSettings) -> None:
        self.settings = settings

    @property
    def issuer(self) -> str:
        return self.settings.issuer

    async def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> str:
        if code_challenge_method != "S256":
            raise BusinessOSError("invalid_pkce", "Authentication failed", status_code=400)
        parameters = urlencode(
            {
                "response_type": "code",
                "scope": "openid profile email",
                "client_id": self.settings.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if "?" in self.settings.authorization_url else "?"
        return f"{self.settings.authorization_url}{separator}{parameters}"

    async def exchange_code(self, *, code: str, redirect_uri: str, pkce_verifier: str) -> str:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.settings.client_id,
            "code_verifier": pkce_verifier,
        }
        if self.settings.client_secret_file:
            payload["client_secret"] = (
                await asyncio.to_thread(
                    Path(self.settings.client_secret_file).read_text, encoding="utf-8"
                )
            ).strip()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            try:
                response = await client.post(self.settings.token_url, data=payload)
                response.raise_for_status()
                token = response.json().get("id_token")
            except (httpx.HTTPError, ValueError, AttributeError):
                raise BusinessOSError(
                    "oidc_exchange_failed", "Authentication failed", status_code=401
                ) from None
        if not isinstance(token, str) or not token:
            raise BusinessOSError("oidc_exchange_failed", "Authentication failed", status_code=401)
        return token


class BrowserSessionRuntime:
    def __init__(
        self,
        settings: BrowserOIDCSettings,
        installation_id: UUID,
        unit_of_work_factory: UnitOfWorkFactory,
        oidc_resolver: OIDCContextResolver,
    ) -> None:
        self.redis: Any = cast(Any, from_url)(settings.redis_url, decode_responses=False)
        self.service = WebSessionApplicationService(
            configuration=WebSessionConfiguration(
                installation_id=installation_id, callback_url=settings.callback_url
            ),
            sessions=RedisWebSessionStore(self.redis),
            transactions=RedisAuthorizationTransactionStore(self.redis),
            oidc=OIDCAuthorizationCodeAdapter(
                {"default": HttpOIDCAuthorizationClient(settings)},
                {"default": oidc_resolver},
            ),
            principal_validator=DatabasePrincipalSessionValidator(
                installation_id=installation_id,
                unit_of_work_factory=unit_of_work_factory,
                tenant_access=DatabaseTenantAccessValidator(installation_id, unit_of_work_factory),
            ),
        )

    async def close(self) -> None:
        await self.redis.aclose()


class BrowserSessionContextResolver:
    def __init__(self, oidc: OIDCContextResolver, runtime: BrowserSessionRuntime) -> None:
        self.oidc = oidc
        self.runtime = runtime

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        from .principal_binding import clear_authenticated_principal

        clear_authenticated_principal()
        handle = cookie_value(identity.headers, SESSION_COOKIE)
        if handle is None:
            return await self.oidc.resolve(identity)
        if identity.headers.get("authorization"):
            raise BusinessOSError(
                "ambiguous_credentials", "Multiple credentials are not accepted", status_code=400
            )
        session = await self.runtime.service.get_session(handle)
        if session is None:
            return RequestContext(
                correlation_id=identity.correlation_id, trace_id=identity.trace_id
            )
        if identity.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            supplied = identity.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied, session.csrf_token):
                raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
            fetch_site = identity.headers.get("sec-fetch-site")
            if fetch_site not in {None, "same-origin", "none"}:
                raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
            origin = identity.headers.get("origin")
            host = identity.headers.get("host")
            if origin is not None and (host is None or origin != f"https://{host}"):
                raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
        context = self.runtime.service.request_context(session, identity)
        bind_authenticated_principal(context, session.principal)
        return context

    async def close(self) -> None:
        await self.runtime.close()
