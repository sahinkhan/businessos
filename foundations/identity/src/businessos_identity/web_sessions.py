"""ADR-009 browser authorization transactions and server-side web sessions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from businessos_tenant import TenantAccessValidator
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from businessos.sdk import (
    BusinessOSError,
    DependencyKey,
    RequestContext,
    RequestIdentity,
    TenantContext,
    UnitOfWorkFactory,
)

from .contracts import PrincipalIdentity
from .models import DEVICES, MEMBERSHIPS, SERVICE_ACCOUNTS, USERS
from .oidc import OIDCContextResolver

SESSION_COOKIE = "__Host-businessos_session"
AUTH_TRANSACTION_COOKIE = "__Host-businessos_auth_txn"
SESSION_PROVIDER = "identity.web-session.store"
AUTH_TRANSACTION_PROVIDER = "identity.oidc-transaction.store"
OIDC_BROWSER_PROVIDER = "identity.oidc-browser.provider"
PRINCIPAL_SESSION_VALIDATOR = "identity.web-session.principal-validator"
WEB_SESSION_CONFIGURATION = "identity.web-session.configuration"
WEB_SESSION_SERVICE = DependencyKey["WebSessionApplicationService"](
    "foundation.identity.web_session_service"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _opaque() -> str:
    return secrets.token_urlsafe(32)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    value = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sanitize_return_path(value: str | None) -> str:
    """Accept application-local paths only and discard unsafe navigation targets."""
    if value is None or value == "":
        return "/"
    parsed = urlsplit(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise BusinessOSError("unsafe_return_path", "Return path is not valid", status_code=400)
    return value


@dataclass(frozen=True, slots=True)
class WebSessionConfiguration:
    installation_id: UUID
    callback_url: str
    absolute_ttl: timedelta = timedelta(hours=8)
    idle_ttl: timedelta = timedelta(minutes=30)
    transaction_ttl: timedelta = timedelta(minutes=5)
    login_attempt_limit: int = 10
    login_attempt_window: timedelta = timedelta(minutes=1)

    def __post_init__(self) -> None:
        if not self.callback_url.startswith("https://"):
            raise ValueError("OIDC callback URL must use HTTPS")
        if self.absolute_ttl <= timedelta(0) or self.idle_ttl <= timedelta(0):
            raise ValueError("Session lifetimes must be positive")
        if self.transaction_ttl <= timedelta(0) or self.login_attempt_window <= timedelta(0):
            raise ValueError("Authentication transaction lifetimes must be positive")
        if self.login_attempt_limit < 1:
            raise ValueError("Login attempt limit must be positive")

    async def readiness(self) -> None:
        return None


class ActiveScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    enterprise_group_id: UUID | None = None
    legal_entity_id: UUID | None = None
    company_id: UUID | None = None
    business_unit_id: UUID | None = None
    division_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None
    region_id: UUID | None = None
    operating_site_id: UUID | None = None
    warehouse_id: UUID | None = None
    cost_center_id: UUID | None = None
    profit_center_id: UUID | None = None
    project_id: UUID | None = None
    delegation_id: UUID | None = None


class PrincipalProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    type: str
    display_name: str | None = None
    email: str | None = None
    authentication_strength: str


class SessionProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str = "authenticated"
    principal: PrincipalProjection
    active_scope: ActiveScope
    expires_at: datetime
    csrf_token: str


class WebSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "1"
    generation: int = 1
    principal: PrincipalIdentity
    display_name: str | None = None
    email: str | None = None
    provider_id: str
    issued_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    csrf_token: str
    active_scope: ActiveScope
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def live_at(self, instant: datetime) -> bool:
        return (
            self.revoked_at is None
            and instant < self.idle_expires_at
            and instant < self.absolute_expires_at
        )


class AuthorizationTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: str
    nonce: str
    pkce_verifier: str
    pkce_challenge: str
    browser_binding_digest: str
    provider_id: str
    expected_issuer: str
    return_to: str
    issued_at: datetime
    expires_at: datetime


class LoginStart(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorization_url: str
    expires_at: datetime
    browser_binding: str = Field(exclude=True)


class AuthenticatedPrincipal(BaseModel):
    """Validated output of the external-provider adapter; contains no provider tokens."""

    model_config = ConfigDict(frozen=True)
    identity: PrincipalIdentity
    display_name: str | None = None
    email: str | None = None


class WebSessionStore(Protocol):
    async def create(self, session: WebSession) -> str: ...
    async def get(self, opaque_session_id: str) -> WebSession | None: ...
    async def touch(
        self, opaque_session_id: str, expected_generation: int, idle_expires_at: datetime
    ) -> WebSession | None: ...
    async def rotate(self, opaque_session_id: str, replacement: WebSession) -> str: ...
    async def revoke(self, opaque_session_id: str, reason: str) -> None: ...
    async def revoke_principal(self, tenant_id: UUID, principal_id: UUID, reason: str) -> None: ...


class AuthorizationTransactionStore(Protocol):
    async def allow_login(self, rate_limit_key: str, limit: int, window_seconds: int) -> bool: ...
    async def create(self, transaction: AuthorizationTransaction) -> None: ...
    async def consume(self, state: str, browser_binding: str) -> AuthorizationTransaction: ...
    async def clear_browser_binding(self, browser_binding: str) -> None: ...


class OIDCBrowserProvider(Protocol):
    """External IdP boundary; implementations exchange and validate provider credentials."""

    async def authorization_url(
        self,
        *,
        provider_id: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> tuple[str, str]: ...

    async def exchange_code(
        self,
        *,
        provider_id: str,
        code: str,
        redirect_uri: str,
        pkce_verifier: str,
        expected_nonce: str,
        expected_issuer: str,
    ) -> AuthenticatedPrincipal: ...


class OIDCAuthorizationClient(Protocol):
    """Provider-specific network client that keeps token exchange server-side."""

    @property
    def issuer(self) -> str: ...

    async def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str, pkce_verifier: str) -> str: ...


class OIDCAuthorizationCodeAdapter:
    """OIDC BFF adapter composing provider I/O with certified Identity validation."""

    def __init__(
        self,
        clients: Mapping[str, OIDCAuthorizationClient],
        resolvers: Mapping[str, OIDCContextResolver],
    ) -> None:
        self._clients = dict(clients)
        self._resolvers = dict(resolvers)

    def _provider(self, provider_id: str) -> tuple[OIDCAuthorizationClient, OIDCContextResolver]:
        client = self._clients.get(provider_id)
        resolver = self._resolvers.get(provider_id)
        if client is None or resolver is None:
            raise BusinessOSError(
                "oidc_provider_not_found", "Authentication provider is unavailable", status_code=404
            )
        return client, resolver

    async def authorization_url(
        self,
        *,
        provider_id: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> tuple[str, str]:
        if code_challenge_method != "S256":
            raise BusinessOSError(
                "invalid_pkce_method", "Authentication request is not valid", status_code=422
            )
        client, _ = self._provider(provider_id)
        url = await client.authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
        return url, client.issuer

    async def exchange_code(
        self,
        *,
        provider_id: str,
        code: str,
        redirect_uri: str,
        pkce_verifier: str,
        expected_nonce: str,
        expected_issuer: str,
    ) -> AuthenticatedPrincipal:
        client, resolver = self._provider(provider_id)
        if not hmac.compare_digest(client.issuer, expected_issuer):
            raise BusinessOSError("invalid_oidc_issuer", "Authentication failed", status_code=401)
        id_token = await client.exchange_code(
            code=code,
            redirect_uri=redirect_uri,
            pkce_verifier=pkce_verifier,
        )
        identity = await resolver.authenticate_token(id_token, expected_nonce=expected_nonce)
        return AuthenticatedPrincipal(identity=identity)


class PrincipalSessionValidator(Protocol):
    """Revalidate active tenant, principal, and effective membership under trusted storage."""

    async def validate(self, principal: PrincipalIdentity) -> None: ...


class DatabasePrincipalSessionValidator:
    """Revalidate tenant, principal, and effective membership under tenant RLS."""

    def __init__(
        self,
        *,
        installation_id: UUID,
        unit_of_work_factory: UnitOfWorkFactory,
        tenant_access: TenantAccessValidator,
    ) -> None:
        self._installation_id = installation_id
        self._unit_of_work_factory = unit_of_work_factory
        self._tenant_access = tenant_access

    async def validate(self, principal: PrincipalIdentity) -> None:
        await self._tenant_access.require_active(principal.tenant_id)
        principal_table = {
            "user": USERS,
            "service_account": SERVICE_ACCOUNTS,
            "device": DEVICES,
        }.get(principal.principal_type)
        if principal_table is None:
            raise BusinessOSError(
                "invalid_membership", "Active tenant membership is required", status_code=403
            )
        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=principal.tenant_id,
            principal_id=principal.principal_id,
            authentication_strength=str(principal.authentication_strength),
        )
        now = _now()
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            result = await unit_of_work.persistence.execute(
                select(MEMBERSHIPS.c.id)
                .join(
                    principal_table,
                    (principal_table.c.tenant_id == MEMBERSHIPS.c.tenant_id)
                    & (principal_table.c.id == MEMBERSHIPS.c.principal_id),
                )
                .where(
                    MEMBERSHIPS.c.tenant_id == principal.tenant_id,
                    MEMBERSHIPS.c.principal_id == principal.principal_id,
                    MEMBERSHIPS.c.principal_type == principal.principal_type,
                    MEMBERSHIPS.c.status == "active",
                    principal_table.c.active.is_(True),
                    (MEMBERSHIPS.c.valid_from.is_(None) | (MEMBERSHIPS.c.valid_from <= now)),
                    (MEMBERSHIPS.c.valid_until.is_(None) | (MEMBERSHIPS.c.valid_until >= now)),
                )
            )
            active = result.scalar_one_or_none()
        if active is None:
            raise BusinessOSError(
                "invalid_membership", "Active tenant membership is required", status_code=403
            )


class InMemoryWebSessionStore:
    """Deterministic test provider. Production composition must choose a durable provider."""

    test_only = True

    def __init__(self) -> None:
        self._sessions: dict[str, WebSession] = {}
        self._lock = asyncio.Lock()

    async def readiness(self) -> None:
        return None

    async def create(self, session: WebSession) -> str:
        handle = _opaque()
        async with self._lock:
            self._sessions[_digest(handle)] = session
        return handle

    async def get(self, opaque_session_id: str) -> WebSession | None:
        async with self._lock:
            session = self._sessions.get(_digest(opaque_session_id))
            if session is not None and not session.live_at(_now()):
                self._sessions.pop(_digest(opaque_session_id), None)
                return None
            return session

    async def touch(
        self, opaque_session_id: str, expected_generation: int, idle_expires_at: datetime
    ) -> WebSession | None:
        key = _digest(opaque_session_id)
        async with self._lock:
            current = self._sessions.get(key)
            now = _now()
            if (
                current is None
                or current.generation != expected_generation
                or not current.live_at(now)
            ):
                self._sessions.pop(key, None)
                return None
            touched = current.model_copy(
                update={
                    "last_seen_at": now,
                    "idle_expires_at": min(idle_expires_at, current.absolute_expires_at),
                }
            )
            self._sessions[key] = touched
            return touched

    async def rotate(self, opaque_session_id: str, replacement: WebSession) -> str:
        old_key = _digest(opaque_session_id)
        handle = _opaque()
        async with self._lock:
            if self._sessions.pop(old_key, None) is None:
                raise BusinessOSError("invalid_session", "Session is not valid", status_code=401)
            self._sessions[_digest(handle)] = replacement
        return handle

    async def revoke(self, opaque_session_id: str, reason: str) -> None:
        async with self._lock:
            self._sessions.pop(_digest(opaque_session_id), None)

    async def revoke_principal(self, tenant_id: UUID, principal_id: UUID, reason: str) -> None:
        async with self._lock:
            self._sessions = {
                key: value
                for key, value in self._sessions.items()
                if not (
                    value.principal.tenant_id == tenant_id
                    and value.principal.principal_id == principal_id
                )
            }


class InMemoryAuthorizationTransactionStore:
    test_only = True

    def __init__(self) -> None:
        self._transactions: dict[str, AuthorizationTransaction] = {}
        self._bindings: dict[str, set[str]] = {}
        self._consumed: dict[str, datetime] = {}
        self._login_attempts: dict[str, tuple[int, datetime]] = {}
        self._lock = asyncio.Lock()

    async def readiness(self) -> None:
        return None

    async def allow_login(self, rate_limit_key: str, limit: int, window_seconds: int) -> bool:
        now = _now()
        key = _digest(rate_limit_key)
        async with self._lock:
            count, expires_at = self._login_attempts.get(
                key, (0, now + timedelta(seconds=window_seconds))
            )
            if expires_at <= now:
                count, expires_at = 0, now + timedelta(seconds=window_seconds)
            count += 1
            self._login_attempts[key] = (count, expires_at)
            return count <= limit

    async def create(self, transaction: AuthorizationTransaction) -> None:
        async with self._lock:
            self._transactions[_digest(transaction.state)] = transaction
            self._bindings.setdefault(transaction.browser_binding_digest, set()).add(
                _digest(transaction.state)
            )

    async def consume(self, state: str, browser_binding: str) -> AuthorizationTransaction:
        state_key = _digest(state)
        binding_key = _digest(browser_binding)
        async with self._lock:
            self._purge_consumed()
            if state_key in self._consumed:
                raise BusinessOSError(
                    "authentication_transaction_replayed",
                    "Authentication transaction was already consumed",
                    status_code=409,
                )
            transaction = self._transactions.pop(state_key, None)
            if transaction is None:
                await self._clear_binding_locked(binding_key)
                raise BusinessOSError(
                    "invalid_authentication_transaction",
                    "Authentication transaction is not valid",
                    status_code=401,
                )
            self._bindings.get(transaction.browser_binding_digest, set()).discard(state_key)
            self._consumed[state_key] = transaction.expires_at
            if transaction.expires_at <= _now():
                raise BusinessOSError(
                    "expired_authentication_transaction",
                    "Authentication transaction has expired",
                    status_code=401,
                )
            if not hmac.compare_digest(transaction.browser_binding_digest, binding_key):
                await self._clear_binding_locked(binding_key)
                raise BusinessOSError(
                    "invalid_browser_binding", "Browser binding is not valid", status_code=401
                )
            return transaction

    async def clear_browser_binding(self, browser_binding: str) -> None:
        async with self._lock:
            await self._clear_binding_locked(_digest(browser_binding))

    async def _clear_binding_locked(self, binding_key: str) -> None:
        for state_key in self._bindings.pop(binding_key, set()):
            transaction = self._transactions.pop(state_key, None)
            if transaction is not None:
                self._consumed[state_key] = transaction.expires_at

    def _purge_consumed(self) -> None:
        now = _now()
        self._consumed = {key: expiry for key, expiry in self._consumed.items() if expiry > now}


class RedisWebSessionStore:
    """Redis session provider using digest-only keys and atomic rotation/revocation."""

    def __init__(self, redis: Any, namespace: str = "businessos:web-session") -> None:
        self._redis = redis
        self._namespace = namespace

    async def readiness(self) -> None:
        await self._redis.ping()

    def _key(self, handle: str) -> str:
        return f"{self._namespace}:session:{_digest(handle)}"

    def _principal_index(self, tenant_id: UUID, principal_id: UUID) -> str:
        return f"{self._namespace}:principal:{tenant_id}:{principal_id}"

    @staticmethod
    def _ttl(session: WebSession) -> int:
        return max(1, int((session.absolute_expires_at - _now()).total_seconds()))

    async def create(self, session: WebSession) -> str:
        principal_index = self._principal_index(
            session.principal.tenant_id, session.principal.principal_id
        )
        ttl = self._ttl(session)
        script = """
        if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        redis.call('SADD', KEYS[2], KEYS[1])
        local index_ttl = redis.call('TTL', KEYS[2])
        if index_ttl < tonumber(ARGV[2]) then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
        return 1
        """
        while True:
            handle = _opaque()
            created = await self._redis.eval(
                script,
                2,
                self._key(handle),
                principal_index,
                session.model_dump_json(),
                ttl,
            )
            if created == 1:
                return handle

    async def get(self, opaque_session_id: str) -> WebSession | None:
        raw = await self._redis.get(self._key(opaque_session_id))
        if raw is None:
            return None
        session = WebSession.model_validate_json(raw)
        if not session.live_at(_now()):
            await self.revoke(opaque_session_id, "expired")
            return None
        return session

    async def touch(
        self, opaque_session_id: str, expected_generation: int, idle_expires_at: datetime
    ) -> WebSession | None:
        current = await self.get(opaque_session_id)
        if current is None or current.generation != expected_generation:
            return None
        now = _now()
        replacement = current.model_copy(
            update={
                "last_seen_at": now,
                "idle_expires_at": min(idle_expires_at, current.absolute_expires_at),
            }
        )
        script = """
        local function sortable_instant(value)
            local year, month, day, hour, minute, second, fraction = string.match(
                value,
                '^(%d%d%d%d)%-(%d%d)%-(%d%d)T(%d%d):(%d%d):(%d%d)%.?(%d*)'
            )
            if not year then return nil end
            fraction = string.sub(fraction .. '000000', 1, 6)
            return year .. month .. day .. hour .. minute .. second .. fraction
        end
        local raw = redis.call('GET', KEYS[1])
        if not raw then return false end
        local current = cjson.decode(raw)
        if tonumber(current.generation) ~= tonumber(ARGV[1]) then return false end
        local now = sortable_instant(ARGV[4])
        local idle_expiry = sortable_instant(current.idle_expires_at)
        local absolute_expiry = sortable_instant(current.absolute_expires_at)
        if not now or not idle_expiry or not absolute_expiry then return false end
        if idle_expiry <= now or absolute_expiry <= now then return false end
        local touched = cjson.decode(ARGV[2])
        current.last_seen_at = touched.last_seen_at
        current.idle_expires_at = touched.idle_expires_at
        local encoded = cjson.encode(current)
        redis.call('SET', KEYS[1], encoded, 'EX', ARGV[3])
        return encoded
        """
        changed = await self._redis.eval(
            script,
            1,
            self._key(opaque_session_id),
            expected_generation,
            replacement.model_dump_json(),
            self._ttl(replacement),
            now.isoformat(timespec="microseconds"),
        )
        return WebSession.model_validate_json(changed) if changed else None

    async def rotate(self, opaque_session_id: str, replacement: WebSession) -> str:
        handle = _opaque()
        principal_index = self._principal_index(
            replacement.principal.tenant_id, replacement.principal.principal_id
        )
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
        if redis.call('EXISTS', KEYS[2]) == 1 then return -1 end
        redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
        redis.call('DEL', KEYS[1])
        redis.call('SREM', KEYS[3], KEYS[1])
        redis.call('SADD', KEYS[3], KEYS[2])
        local index_ttl = redis.call('TTL', KEYS[3])
        if index_ttl < tonumber(ARGV[2]) then redis.call('EXPIRE', KEYS[3], ARGV[2]) end
        return 1
        """
        changed = await self._redis.eval(
            script,
            3,
            self._key(opaque_session_id),
            self._key(handle),
            principal_index,
            replacement.model_dump_json(),
            self._ttl(replacement),
        )
        if changed != 1:
            raise BusinessOSError("invalid_session", "Session is not valid", status_code=401)
        return handle

    async def revoke(self, opaque_session_id: str, reason: str) -> None:
        session_key = self._key(opaque_session_id)
        raw = await self._redis.get(session_key)
        if raw is None:
            return
        session = WebSession.model_validate_json(raw)
        principal_index = self._principal_index(
            session.principal.tenant_id, session.principal.principal_id
        )
        pipe = self._redis.pipeline(transaction=True)
        pipe.delete(session_key)
        pipe.srem(principal_index, session_key)
        await pipe.execute()

    async def revoke_principal(self, tenant_id: UUID, principal_id: UUID, reason: str) -> None:
        index = self._principal_index(tenant_id, principal_id)
        keys = await self._redis.smembers(index)
        if keys:
            await self._redis.delete(*keys, index)


class RedisAuthorizationTransactionStore:
    def __init__(self, redis: Any, namespace: str = "businessos:oidc-transaction") -> None:
        self._redis = redis
        self._namespace = namespace

    async def readiness(self) -> None:
        await self._redis.ping()

    async def allow_login(self, rate_limit_key: str, limit: int, window_seconds: int) -> bool:
        key = f"{self._namespace}:login-rate:{_digest(rate_limit_key)}"
        script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        return count
        """
        count = await self._redis.eval(script, 1, key, max(1, window_seconds))
        return int(count) <= limit

    def _state_key(self, state: str) -> str:
        return f"{self._namespace}:state:{_digest(state)}"

    def _binding_key(self, binding_digest: str) -> str:
        return f"{self._namespace}:binding:{binding_digest}"

    async def create(self, transaction: AuthorizationTransaction) -> None:
        ttl = max(1, int((transaction.expires_at - _now()).total_seconds()))
        state_key = self._state_key(transaction.state)
        binding_key = self._binding_key(transaction.browser_binding_digest)
        script = """
        if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        redis.call('SADD', KEYS[2], KEYS[1])
        redis.call('EXPIRE', KEYS[2], ARGV[2])
        return 1
        """
        created = await self._redis.eval(
            script,
            2,
            state_key,
            binding_key,
            transaction.model_dump_json(),
            ttl,
        )
        if created != 1:
            raise BusinessOSError(
                "authentication_transaction_collision",
                "Authentication transaction could not be created",
                status_code=503,
            )

    async def consume(self, state: str, browser_binding: str) -> AuthorizationTransaction:
        state_key = self._state_key(state)
        replay_key = f"{state_key}:consumed"
        script = """
        if redis.call('EXISTS', KEYS[2]) == 1 then return '__REPLAY__' end
        local value = redis.call('GET', KEYS[1])
        if not value then return false end
        redis.call('DEL', KEYS[1])
        redis.call('SET', KEYS[2], '1', 'EX', ARGV[1], 'NX')
        return value
        """
        raw = await self._redis.eval(script, 2, state_key, replay_key, 300)
        if raw in (b"__REPLAY__", "__REPLAY__"):
            raise BusinessOSError(
                "authentication_transaction_replayed",
                "Authentication transaction was already consumed",
                status_code=409,
            )
        if raw is None:
            await self.clear_browser_binding(browser_binding)
            raise BusinessOSError(
                "invalid_authentication_transaction",
                "Authentication transaction is not valid",
                status_code=401,
            )
        transaction = AuthorizationTransaction.model_validate_json(raw)
        binding_digest = _digest(browser_binding)
        await self._redis.srem(self._binding_key(transaction.browser_binding_digest), state_key)
        if transaction.expires_at <= _now():
            raise BusinessOSError(
                "expired_authentication_transaction",
                "Authentication transaction has expired",
                status_code=401,
            )
        if not hmac.compare_digest(transaction.browser_binding_digest, binding_digest):
            await self.clear_browser_binding(browser_binding)
            raise BusinessOSError(
                "invalid_browser_binding", "Browser binding is not valid", status_code=401
            )
        return transaction

    async def clear_browser_binding(self, browser_binding: str) -> None:
        key = self._binding_key(_digest(browser_binding))
        script = """
        local states = redis.call('SMEMBERS', KEYS[1])
        for _, state_key in ipairs(states) do
            redis.call('DEL', state_key)
            redis.call('SET', state_key .. ':consumed', '1', 'EX', ARGV[1], 'NX')
        end
        redis.call('DEL', KEYS[1])
        return #states
        """
        await self._redis.eval(script, 1, key, 300)


class WebSessionApplicationService:
    """Protocol-neutral application boundary shared by OIDC and future SAML adapters."""

    def __init__(
        self,
        *,
        configuration: WebSessionConfiguration,
        sessions: WebSessionStore,
        transactions: AuthorizationTransactionStore,
        oidc: OIDCBrowserProvider,
        principal_validator: PrincipalSessionValidator,
    ) -> None:
        self.configuration = configuration
        self.sessions = sessions
        self.transactions = transactions
        self.oidc = oidc
        self.principal_validator = principal_validator

    async def start_login(
        self, provider_id: str, return_to: str | None, *, rate_limit_key: str = "unknown"
    ) -> LoginStart:
        allowed = await self.transactions.allow_login(
            rate_limit_key,
            self.configuration.login_attempt_limit,
            max(1, int(self.configuration.login_attempt_window.total_seconds())),
        )
        if not allowed:
            raise BusinessOSError(
                "authentication_rate_limited",
                "Authentication initiation rate limit exceeded",
                status_code=429,
            )
        now = _now()
        state, nonce, verifier, binding = _opaque(), _opaque(), _opaque(), _opaque()
        challenge = _pkce_challenge(verifier)
        authorization_url, issuer = await self.oidc.authorization_url(
            provider_id=provider_id,
            redirect_uri=self.configuration.callback_url,
            state=state,
            nonce=nonce,
            code_challenge=challenge,
            code_challenge_method="S256",
        )
        transaction = AuthorizationTransaction(
            state=state,
            nonce=nonce,
            pkce_verifier=verifier,
            pkce_challenge=challenge,
            browser_binding_digest=_digest(binding),
            provider_id=provider_id,
            expected_issuer=issuer,
            return_to=sanitize_return_path(return_to),
            issued_at=now,
            expires_at=now + self.configuration.transaction_ttl,
        )
        await self.transactions.create(transaction)
        return LoginStart(
            authorization_url=authorization_url,
            expires_at=transaction.expires_at,
            browser_binding=binding,
        )

    async def complete_oidc_login(
        self, *, state: str, code: str, browser_binding: str
    ) -> tuple[str, WebSession, str]:
        transaction = await self.transactions.consume(state, browser_binding)
        try:
            authenticated = await self.oidc.exchange_code(
                provider_id=transaction.provider_id,
                code=code,
                redirect_uri=self.configuration.callback_url,
                pkce_verifier=transaction.pkce_verifier,
                expected_nonce=transaction.nonce,
                expected_issuer=transaction.expected_issuer,
            )
            handle, session = await self.create_session(
                authenticated, provider_id=transaction.provider_id
            )
            return handle, session, transaction.return_to
        finally:
            await self.transactions.clear_browser_binding(browser_binding)

    async def create_session(
        self, authenticated: AuthenticatedPrincipal, *, provider_id: str
    ) -> tuple[str, WebSession]:
        now = _now()
        identity = authenticated.identity
        session = WebSession(
            principal=identity,
            display_name=authenticated.display_name,
            email=authenticated.email,
            provider_id=provider_id,
            issued_at=now,
            last_seen_at=now,
            idle_expires_at=now + self.configuration.idle_ttl,
            absolute_expires_at=now + self.configuration.absolute_ttl,
            csrf_token=_opaque(),
            active_scope=ActiveScope(tenant_id=identity.tenant_id),
        )
        return await self.sessions.create(session), session

    async def get_session(self, handle: str, *, touch: bool = True) -> WebSession | None:
        session = await self.sessions.get(handle)
        if session is None:
            return None
        try:
            await self.principal_validator.validate(session.principal)
        except Exception:
            await self.sessions.revoke(handle, "principal-revalidation-failed")
            raise
        if touch:
            session = await self.sessions.touch(
                handle,
                session.generation,
                _now() + self.configuration.idle_ttl,
            )
        return session

    async def rotate_scope(self, handle: str, scope: ActiveScope) -> tuple[str, WebSession]:
        session = await self.get_session(handle, touch=False)
        if session is None or scope.tenant_id != session.principal.tenant_id:
            raise BusinessOSError("invalid_session", "Session is not valid", status_code=401)
        replacement = session.model_copy(
            update={
                "generation": session.generation + 1,
                "csrf_token": _opaque(),
                "active_scope": scope,
                "last_seen_at": _now(),
            }
        )
        return await self.sessions.rotate(handle, replacement), replacement

    async def logout(self, handle: str) -> None:
        await self.sessions.revoke(handle, "logout")

    def project(self, session: WebSession) -> SessionProjection:
        return SessionProjection(
            principal=PrincipalProjection(
                id=session.principal.principal_id,
                tenant_id=session.principal.tenant_id,
                type=session.principal.principal_type,
                display_name=session.display_name,
                email=session.email,
                authentication_strength=str(session.principal.authentication_strength),
            ),
            active_scope=session.active_scope,
            expires_at=min(session.idle_expires_at, session.absolute_expires_at),
            csrf_token=session.csrf_token,
        )

    def request_context(self, session: WebSession, identity: RequestIdentity) -> RequestContext:
        scope = session.active_scope
        return RequestContext(
            correlation_id=identity.correlation_id,
            trace_id=identity.trace_id,
            tenant=TenantContext(
                installation_id=self.configuration.installation_id,
                tenant_id=session.principal.tenant_id,
                principal_id=session.principal.principal_id,
                authentication_strength=str(session.principal.authentication_strength),
                active_company_id=scope.company_id,
                enterprise_group_id=scope.enterprise_group_id,
                legal_entity_id=scope.legal_entity_id,
                business_unit_id=scope.business_unit_id,
                division_id=scope.division_id,
                department_id=scope.department_id,
                team_id=scope.team_id,
                region_id=scope.region_id,
                operating_site_id=scope.operating_site_id,
                warehouse_id=scope.warehouse_id,
                cost_center_id=scope.cost_center_id,
                profit_center_id=scope.profit_center_id,
                project_id=scope.project_id,
                delegation_id=scope.delegation_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class WebSessionContract:
    version: str = "1.0"
    service: str = "businessos_identity.WebSessionApplicationService"
    store: str = "businessos_identity.WebSessionStore"
    saml_entry: str = "businessos_identity.AuthenticatedPrincipal"


def cookie_value(headers: Mapping[str, str], name: str) -> str | None:
    for part in headers.get("cookie", "").split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value
    return None


def session_cookie(handle: str, expires_at: datetime) -> str:
    max_age = max(0, int((expires_at - _now()).total_seconds()))
    return f"{SESSION_COOKIE}={handle}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite=Lax"


def transaction_cookie(binding: str, expires_at: datetime) -> str:
    max_age = max(0, int((expires_at - _now()).total_seconds()))
    return (
        f"{AUTH_TRANSACTION_COOKIE}={binding}; Path=/; Max-Age={max_age}; "
        "Secure; HttpOnly; SameSite=Lax"
    )


def expire_cookie(name: str) -> str:
    return f"{name}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"
