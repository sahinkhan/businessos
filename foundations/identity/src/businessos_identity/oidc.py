"""OIDC verification and trusted membership-derived request context."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

import jwt
from businessos_tenant import TenantAccessValidator
from jwt import InvalidTokenError, PyJWKClient
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, select

from businessos.sdk import (
    BusinessOSError,
    RequestContext,
    RequestIdentity,
    TenantContext,
    UnitOfWorkFactory,
)

from .models import EXTERNAL_IDENTITIES, MEMBERSHIPS, USERS


class VerifiedOIDCClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    iss: str
    sub: str
    aud: str | tuple[str, ...]
    exp: int
    iat: int
    businessos_tenant_id: UUID
    acr: str | None = None
    amr: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OIDCConfiguration:
    issuer: str
    audience: str
    jwks_uri: str
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.issuer.startswith("https://") or not self.jwks_uri.startswith("https://"):
            raise ValueError("OIDC issuer and JWKS URI must use HTTPS")
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
        if not self.algorithms or not set(self.algorithms) <= allowed:
            raise ValueError("OIDC algorithms must use an approved asymmetric allowlist")


class SigningKeyResolver(Protocol):
    async def resolve(self, token: str) -> Any: ...


class RemoteJWKSetResolver:
    """PyJWT-backed HTTPS JWK resolver with bounded cache lifetime."""

    def __init__(self, jwks_uri: str, *, cache_seconds: int = 300) -> None:
        if not jwks_uri.startswith("https://"):
            raise ValueError("OIDC JWKS URI must use HTTPS")
        self._client = PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=cache_seconds)

    async def resolve(self, token: str) -> Any:
        return await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)


class OIDCTokenVerifier:
    def __init__(self, configuration: OIDCConfiguration, keys: SigningKeyResolver) -> None:
        self._configuration = configuration
        self._keys = keys

    async def verify(self, token: str) -> VerifiedOIDCClaims:
        try:
            key = await self._keys.resolve(token)
            payload = jwt.decode(
                token,
                key,
                algorithms=list(self._configuration.algorithms),
                audience=self._configuration.audience,
                issuer=self._configuration.issuer,
                leeway=self._configuration.leeway_seconds,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "businessos_tenant_id"]},
            )
            return VerifiedOIDCClaims.model_validate(payload)
        except (InvalidTokenError, ValidationError, ValueError, TypeError):
            raise BusinessOSError(
                "invalid_token", "Authentication credential is not valid", status_code=401
            ) from None


class OIDCContextResolver:
    """Trust a signed tenant claim only after active membership is proven under RLS."""

    def __init__(
        self,
        *,
        installation_id: UUID,
        verifier: OIDCTokenVerifier,
        unit_of_work_factory: UnitOfWorkFactory,
        tenant_access: TenantAccessValidator,
    ) -> None:
        self._installation_id = installation_id
        self._verifier = verifier
        self._unit_of_work_factory = unit_of_work_factory
        self._tenant_access = tenant_access

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        authorization = identity.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential.strip():
            return RequestContext(
                correlation_id=identity.correlation_id, trace_id=identity.trace_id
            )
        claims = await self._verifier.verify(credential.strip())
        await self._tenant_access.require_active(claims.businessos_tenant_id)
        principal_id, _scopes = await self._membership(claims)
        strength = claims.acr or ("mfa" if "mfa" in claims.amr else "oidc")
        return RequestContext(
            correlation_id=identity.correlation_id,
            trace_id=identity.trace_id,
            tenant=TenantContext(
                installation_id=self._installation_id,
                tenant_id=claims.businessos_tenant_id,
                principal_id=principal_id,
                authentication_strength=strength,
            ),
        )

    async def _membership(
        self, claims: VerifiedOIDCClaims
    ) -> tuple[UUID, tuple[dict[str, str], ...]]:
        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=claims.businessos_tenant_id,
            principal_id=UUID(int=0),
            authentication_strength="oidc-pending-membership",
        )
        now = datetime.now(UTC)
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            result = await unit_of_work.persistence.execute(
                select(EXTERNAL_IDENTITIES.c.user_id, MEMBERSHIPS.c.scopes)
                .join(
                    USERS,
                    and_(
                        USERS.c.tenant_id == EXTERNAL_IDENTITIES.c.tenant_id,
                        USERS.c.id == EXTERNAL_IDENTITIES.c.user_id,
                    ),
                )
                .join(
                    MEMBERSHIPS,
                    and_(
                        MEMBERSHIPS.c.tenant_id == USERS.c.tenant_id,
                        MEMBERSHIPS.c.principal_id == USERS.c.id,
                        MEMBERSHIPS.c.principal_type == "user",
                    ),
                )
                .where(
                    EXTERNAL_IDENTITIES.c.tenant_id == claims.businessos_tenant_id,
                    EXTERNAL_IDENTITIES.c.issuer == claims.iss,
                    EXTERNAL_IDENTITIES.c.subject == claims.sub,
                    USERS.c.active.is_(True),
                    MEMBERSHIPS.c.status == "active",
                    (MEMBERSHIPS.c.valid_from.is_(None) | (MEMBERSHIPS.c.valid_from <= now)),
                    (MEMBERSHIPS.c.valid_until.is_(None) | (MEMBERSHIPS.c.valid_until >= now)),
                )
            )
            row = result.one_or_none()
        if row is None:
            raise BusinessOSError(
                "invalid_membership", "Active tenant membership is required", status_code=403
            )
        raw_scopes = cast(Sequence[Mapping[str, Any]], row.scopes)
        scopes = tuple(
            {str(key): str(value) for key, value in scope.items()} for scope in raw_scopes
        )
        return cast(UUID, row.user_id), scopes
