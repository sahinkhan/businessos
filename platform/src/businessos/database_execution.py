"""Protected, exact-registration database execution authority (ADR-022)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.activation import ContributionGeneration
from businessos.context import TenantContext
from businessos.dependency_entitlement import internal_valid_restricted_dependency_entitlement
from businessos.errors import ConfigurationError
from businessos.persistence.uow import SQLAlchemyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from businessos.messages import Command, _OwnedHandler


GOVERNANCE_PROFILE = "foundation.data_governance"
GOVERNANCE_ROLE = "businessos_governance"
_GOVERNANCE_COMMANDS = frozenset(
    {
        "CreateRetentionPolicyCommand",
        "CreateRetentionPolicyV2Command",
        "PlaceLegalHoldCommand",
        "ReleaseLegalHoldCommand",
    }
)
_GOVERNANCE_COMMAND_MODULE = "businessos_data_governance.module"


@dataclass(frozen=True, slots=True)
class _Registration:
    registered: _OwnedHandler
    command_type: type[Command]
    generation: ContributionGeneration


class _GovernancePool:
    def __init__(self, url: str, *, size: int, timeout: float, database_name: str) -> None:
        if not url.startswith("postgresql+psycopg://"):
            raise ConfigurationError("Protected database URL must use psycopg")
        self.database_name = database_name
        # A bounded QueuePool is retained, while every checkout opens a new physical
        # connection. This trades handshake cost for a hard reset of all session GUCs,
        # SET ROLE, search_path, prepared statements, and transaction state.
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=size,
            max_overflow=0,
            pool_timeout=timeout,
            pool_pre_ping=True,
            pool_recycle=0,
        )
        self.sessions = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
        )

    async def validate(self) -> None:
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    text("SELECT current_database(), current_user, session_user")
                )
                if result.one() != (self.database_name, GOVERNANCE_ROLE, GOVERNANCE_ROLE):
                    raise ConfigurationError("Protected database identity mismatch")
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("Protected database profile unavailable") from None

    def for_tenant(self, tenant: TenantContext) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            self.sessions,
            tenant,
            expected_database=self.database_name,
            expected_user=GOVERNANCE_ROLE,
        )

    async def close(self) -> None:
        await self.engine.dispose()


class ProtectedDatabaseExecutionAuthority:
    """Private dispatcher selection and hot credential rotation.

    Only verified first-party ModuleRegistration can record an exact handler.
    The mapping is a protected deployment rule, never a manifest capability.
    """

    def __init__(
        self,
        *,
        governance_url: str | None,
        database_name: str,
        pool_size: int,
        pool_timeout: float,
    ) -> None:
        self._database_name = database_name
        self._pool_size = pool_size
        self._pool_timeout = pool_timeout
        self._active = (
            _GovernancePool(
                governance_url,
                size=pool_size,
                timeout=pool_timeout,
                database_name=database_name,
            )
            if governance_url
            else None
        )
        self._registrations: dict[int, _Registration] = {}
        self._leases: dict[_GovernancePool, int] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @staticmethod
    def _protected_command(owner: str, command_type: type[Command]) -> bool:
        return (
            owner == GOVERNANCE_PROFILE
            and command_type.__module__ == _GOVERNANCE_COMMAND_MODULE
            and command_type.__name__ in _GOVERNANCE_COMMANDS
        )

    @classmethod
    def requires_protected(cls, registered: _OwnedHandler, command_type: type[Command]) -> bool:
        return cls._protected_command(registered.owner, command_type)

    def record_registration(
        self,
        registered: _OwnedHandler,
        command_type: type[Command],
        entitlement: object,
    ) -> None:
        if not self._protected_command(registered.owner, command_type):
            return
        generation = registered.generation
        if (
            generation is None
            or registered.direct_dependencies is None
            or not internal_valid_restricted_dependency_entitlement(
                entitlement, registered.owner, generation
            )
        ):
            return
        self._registrations[id(registered)] = _Registration(registered, command_type, generation)

    def remove_generation(self, generation: ContributionGeneration) -> None:
        self._registrations = {
            key: value
            for key, value in self._registrations.items()
            if value.generation is not generation
        }

    @asynccontextmanager
    async def for_command(
        self, registered: _OwnedHandler, command_type: type[Command], tenant: TenantContext | None
    ) -> AsyncGenerator[UnitOfWork]:
        if not self.requires_protected(registered, command_type):
            raise PermissionError("Command has no protected database execution profile")
        registration = self._registrations.get(id(registered))
        if (
            tenant is None
            or registration is None
            or registration.registered is not registered
            or registration.command_type is not command_type
            or registration.generation is not registered.generation
        ):
            raise PermissionError(
                "Protected database execution requires exact trusted registration"
            )
        async with self._lock:
            pool = self._active
            if pool is None or self._closed:
                raise ConfigurationError("Protected database profile unavailable")
            self._leases[pool] = self._leases.get(pool, 0) + 1
        try:
            yield pool.for_tenant(tenant)
        finally:
            async with self._lock:
                self._leases[pool] -= 1
                last = self._leases[pool] == 0
                if last:
                    del self._leases[pool]
                retired = pool is not self._active
            if last and retired:
                await pool.close()

    async def validate(self) -> None:
        pool = self._active
        if pool is None:
            raise ConfigurationError("Protected database profile unavailable")
        await pool.validate()

    async def rotate(self, url: str) -> None:
        """Validate a new credential before atomic admission cutover.

        Failure revokes new protected admissions; already admitted transactions
        retain their old pool lease until completion.
        """
        replacement = _GovernancePool(
            url,
            size=self._pool_size,
            timeout=self._pool_timeout,
            database_name=self._database_name,
        )
        try:
            await replacement.validate()
        except BaseException:
            await replacement.close()
            async with self._lock:
                old = self._active
                self._active = None
            if old is not None and self._leases.get(old, 0) == 0:
                await old.close()
            raise
        async with self._lock:
            if self._closed:
                await replacement.close()
                raise ConfigurationError("Protected database profile is closed")
            old = self._active
            self._active = replacement
        if old is not None and self._leases.get(old, 0) == 0:
            await old.close()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            old = self._active
            self._active = None
        if old is not None and self._leases.get(old, 0) == 0:
            await old.close()
