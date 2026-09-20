"""OIDC verification and trusted membership-derived request context."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

import jwt
from businessos_tenant import DatabaseTenantAccessValidator, TenantAccessValidator
from jwt import InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWKError
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, select

from businessos.sdk import (
    BusinessOSError,
    RequestContext,
    RequestIdentity,
    TenantContext,
    TransactionalPersistence,
    UnitOfWorkFactory,
)

from .contracts import AuthenticationStrength
from .models import EXTERNAL_IDENTITIES, MEMBERSHIPS, MFA_POLICIES, OIDC_PROVIDERS, USERS


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

    def for_configuration(self, configuration: OIDCConfiguration) -> "OIDCTokenVerifier":
        keys = self._keys
        if configuration.jwks_uri != self._configuration.jwks_uri:
            keys = RemoteJWKSetResolver(configuration.jwks_uri)
        return OIDCTokenVerifier(configuration, keys)

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
        except (
            InvalidTokenError,
            PyJWKClientError,
            PyJWKError,
            ValidationError,
            ValueError,
            TypeError,
        ):
            raise BusinessOSError(
                "invalid_token", "Authentication credential is not valid", status_code=401
            ) from None


class OIDCContextResolver:
    """Trust a signed tenant claim only after active membership is proven under RLS."""

    def __init__(
        self,
        *,
        installation_id: UUID,
        verifier: OIDCTokenVerifier | None = None,
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
        token = credential.strip()
        hint = _unverified_provider_hint(token)
        provider = await self._provider(hint)
        verifier = (
            self._verifier.for_configuration(provider.configuration)
            if self._verifier is not None
            else OIDCTokenVerifier(
                provider.configuration, RemoteJWKSetResolver(provider.configuration.jwks_uri)
            )
        )
        claims = await verifier.verify(token)
        principal_id, _scopes, policy = await self._authority(claims, hint, provider)
        strength = _authentication_strength(claims)
        _enforce_policy(strength, claims.amr, policy)
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

    async def _authority(
        self,
        claims: VerifiedOIDCClaims,
        hint: "_ProviderHint",
        verified_provider: "_ResolvedProvider",
    ) -> tuple[
        UUID,
        tuple[dict[str, str], ...],
        tuple[AuthenticationStrength, tuple[str, ...]] | None,
    ]:
        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=claims.businessos_tenant_id,
            principal_id=UUID(int=0),
            authentication_strength="oidc-pending-membership",
        )
        now = datetime.now(UTC)
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            await self._tenant_access.require_active_in(
                claims.businessos_tenant_id, unit_of_work.persistence, lock=True
            )
            provider = await self._provider_in(unit_of_work.persistence, hint, lock=True)
            if provider != verified_provider:
                raise _invalid_token()
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
                    USERS.c.is_break_glass.is_(False),
                    MEMBERSHIPS.c.status == "active",
                    (MEMBERSHIPS.c.valid_from.is_(None) | (MEMBERSHIPS.c.valid_from <= now)),
                    (MEMBERSHIPS.c.valid_until.is_(None) | (MEMBERSHIPS.c.valid_until > now)),
                )
                .with_for_update(read=True)
            )
            row = result.one_or_none()
            policy_result = await unit_of_work.persistence.execute(
                select(MFA_POLICIES.c.minimum_strength, MFA_POLICIES.c.required_methods)
                .where(MFA_POLICIES.c.tenant_id == claims.businessos_tenant_id)
                .with_for_update(read=True)
            )
            policy_row = policy_result.one_or_none()
        if row is None:
            raise BusinessOSError(
                "invalid_membership", "Active tenant membership is required", status_code=403
            )
        raw_scopes = cast(Sequence[Mapping[str, Any]], row.scopes)
        scopes = tuple(
            {str(key): str(value) for key, value in scope.items()} for scope in raw_scopes
        )
        policy = None
        if policy_row is not None:
            try:
                minimum = AuthenticationStrength(policy_row.minimum_strength)
            except ValueError:
                raise _invalid_token() from None
            policy = (
                minimum,
                tuple(str(value).casefold() for value in policy_row.required_methods),
            )
        return cast(UUID, row.user_id), scopes, policy

    async def _provider(self, hint: "_ProviderHint") -> "_ResolvedProvider":
        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=hint.businessos_tenant_id,
            principal_id=UUID(int=0),
            authentication_strength="oidc-pending-provider",
        )
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            return await self._provider_in(unit_of_work.persistence, hint)

    async def _provider_in(
        self,
        persistence: TransactionalPersistence,
        hint: "_ProviderHint",
        *,
        lock: bool = False,
    ) -> "_ResolvedProvider":
        statement = select(OIDC_PROVIDERS).where(
            OIDC_PROVIDERS.c.tenant_id == hint.businessos_tenant_id,
            OIDC_PROVIDERS.c.issuer == hint.iss,
            OIDC_PROVIDERS.c.active.is_(True),
        )
        if lock:
            statement = statement.with_for_update(read=True)
        result = await persistence.execute(statement)
        rows = tuple(result.mappings())
        matches = [row for row in rows if row["audience"] in hint.audiences]
        if len(matches) != 1:
            raise _invalid_token()
        row = matches[0]
        try:
            configuration = OIDCConfiguration(
                issuer=row["issuer"],
                audience=row["audience"],
                jwks_uri=row["jwks_uri"],
                algorithms=tuple(row["algorithms"]),
            )
        except (TypeError, ValueError):
            raise _invalid_token() from None
        return _ResolvedProvider(cast(UUID, row["id"]), configuration)


def create_context_resolver(
    installation_id: UUID, unit_of_work_factory: UnitOfWorkFactory
) -> OIDCContextResolver:
    """Compose the standard OIDC trust boundary for the shipped ASGI target."""

    return OIDCContextResolver(
        installation_id=installation_id,
        unit_of_work_factory=unit_of_work_factory,
        tenant_access=DatabaseTenantAccessValidator(installation_id, unit_of_work_factory),
    )


class _ProviderHint(BaseModel):
    model_config = ConfigDict(frozen=True)

    iss: str
    aud: str | tuple[str, ...]
    businessos_tenant_id: UUID

    @property
    def audiences(self) -> tuple[str, ...]:
        return (self.aud,) if isinstance(self.aud, str) else self.aud


@dataclass(frozen=True, slots=True)
class _ResolvedProvider:
    provider_id: UUID
    configuration: OIDCConfiguration


def _unverified_provider_hint(token: str) -> _ProviderHint:
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
        return _ProviderHint.model_validate(payload)
    except (InvalidTokenError, ValidationError, ValueError, TypeError):
        raise _invalid_token() from None


def _authentication_strength(claims: VerifiedOIDCClaims) -> AuthenticationStrength:
    methods = {method.casefold() for method in claims.amr}
    acr = claims.acr.casefold() if claims.acr is not None else ""
    if acr == AuthenticationStrength.PHISHING_RESISTANT or "hwk" in methods:
        return AuthenticationStrength.PHISHING_RESISTANT
    if acr == AuthenticationStrength.MFA or "mfa" in methods:
        return AuthenticationStrength.MFA
    if acr == AuthenticationStrength.PASSWORD or "pwd" in methods:
        return AuthenticationStrength.PASSWORD
    return AuthenticationStrength.OIDC


def _enforce_policy(
    actual: AuthenticationStrength,
    methods: tuple[str, ...],
    policy: tuple[AuthenticationStrength, tuple[str, ...]] | None,
) -> None:
    if policy is None:
        return
    required_strength, required_methods = policy
    ranks = {
        AuthenticationStrength.UNSPECIFIED: 0,
        AuthenticationStrength.OIDC: 1,
        AuthenticationStrength.PASSWORD: 2,
        AuthenticationStrength.MFA: 3,
        AuthenticationStrength.PHISHING_RESISTANT: 4,
        AuthenticationStrength.BREAK_GLASS: 5,
    }
    evidence = {value.casefold() for value in methods}
    if ranks[actual] < ranks[required_strength] or not set(required_methods) <= evidence:
        raise _invalid_token()


def _invalid_token() -> BusinessOSError:
    return BusinessOSError(
        "invalid_token", "Authentication credential is not valid", status_code=401
    )
