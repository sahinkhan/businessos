"""Protected, exact-registration database execution authority (ADR-022)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import TenantContext
from businessos.dependency_entitlement import internal_valid_restricted_dependency_entitlement
from businessos.errors import ConfigurationError, NotFoundError
from businessos.persistence.uow import SQLAlchemyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from businessos.messages import Command


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
_TENANT_POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _normalized_policy(expression: object) -> str:
    if not isinstance(expression, str):
        return ""
    return (
        "".join(expression.lower().replace("::text", "").split()).replace("(", "").replace(")", "")
    )


class _ProtectedCommandRegistration(Protocol):
    @property
    def owner(self) -> str: ...

    @property
    def generation(self) -> ContributionGeneration | None: ...

    @property
    def direct_dependencies(self) -> object | None: ...


@dataclass(frozen=True, slots=True)
class _Registration:
    registered: _ProtectedCommandRegistration
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
                role = await connection.execute(
                    text(
                        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                        "rolinherit, rolbypassrls FROM pg_roles WHERE rolname = :role"
                    ),
                    {"role": GOVERNANCE_ROLE},
                )
                if role.one_or_none() != (True, False, False, False, False, False):
                    raise ConfigurationError("Protected database role is unsafe")
                unsafe = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_auth_members AS m JOIN pg_roles AS r "
                        "ON r.oid = m.roleid JOIN pg_roles AS u ON u.oid = m.member "
                        "WHERE r.rolname = :role OR u.rolname = :role "
                        "UNION ALL SELECT 1 FROM pg_database AS d JOIN pg_roles AS r "
                        "ON r.oid = d.datdba WHERE r.rolname = :role "
                        "UNION ALL SELECT 1 FROM pg_namespace AS n JOIN pg_roles AS r "
                        "ON r.oid = n.nspowner WHERE r.rolname = :role "
                        "UNION ALL SELECT 1 FROM pg_class AS c JOIN pg_roles AS r "
                        "ON r.oid = c.relowner WHERE r.rolname = :role "
                        "UNION ALL SELECT 1 FROM pg_proc AS p JOIN pg_roles AS r "
                        "ON r.oid = p.proowner WHERE r.rolname = :role LIMIT 1"
                    ),
                    {"role": GOVERNANCE_ROLE},
                )
                if unsafe.first() is not None:
                    raise ConfigurationError("Protected database role is unsafe")
                ordinary_membership = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_auth_members AS link "
                        "JOIN pg_roles AS member ON member.oid = link.member "
                        "JOIN pg_roles AS granted ON granted.oid = link.roleid "
                        "WHERE member.rolname IN ('businessos_app', 'businessos_worker') "
                        "AND NOT (member.rolname = 'businessos_worker' "
                        "AND granted.rolname = 'businessos_app') LIMIT 1"
                    )
                )
                if ordinary_membership.first() is not None:
                    raise ConfigurationError("Ordinary database role membership is unsafe")
                protected = (
                    ("platform_gov", "retention_policies", "retention_policies_governance_tenant"),
                    ("platform_gov", "legal_holds", "legal_holds_governance_tenant"),
                    ("platform_audit", "audit_logs", "audit_logs_governance_tenant"),
                    ("eventing", "outbox_messages", "outbox_messages_governance_tenant"),
                )
                for schema, table_name, policy_name in protected:
                    qualified = f"{schema}.{table_name}"
                    state = await connection.execute(
                        text(
                            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class AS c "
                            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = :schema AND c.relname = :table"
                        ),
                        {"schema": schema, "table": table_name},
                    )
                    if state.one_or_none() != (True, True):
                        raise ConfigurationError("Protected database RLS is unsafe")
                    policies = await connection.execute(
                        text(
                            "SELECT policyname, roles, cmd, qual, with_check "
                            "FROM pg_policies WHERE schemaname = :schema AND tablename = :table "
                            "AND (roles @> ARRAY['public']::name[] "
                            "OR roles @> ARRAY[:role]::name[])"
                        ),
                        {"schema": schema, "table": table_name, "role": GOVERNANCE_ROLE},
                    )
                    applicable = policies.all()
                    if (
                        len(applicable) != 1
                        or applicable[0][:3] != (policy_name, [GOVERNANCE_ROLE], "ALL")
                        or any(
                            _normalized_policy(expression) != _normalized_policy(_TENANT_POLICY)
                            for expression in applicable[0][3:]
                        )
                    ):
                        raise ConfigurationError("Protected database RLS policy is unsafe")
                    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                        for role_name in ("businessos_app", "businessos_worker"):
                            result = await connection.execute(
                                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                                {"role": role_name, "table": qualified, "privilege": privilege},
                            )
                            if schema == "platform_gov" and result.scalar_one():
                                raise ConfigurationError(
                                    "Ordinary Governance mutation remains available"
                                )
                    if schema == "platform_gov":
                        for role_name in ("businessos_app", "businessos_worker"):
                            for privilege in ("INSERT", "UPDATE"):
                                result = await connection.execute(
                                    text(
                                        "SELECT has_any_column_privilege(:role, :table, :privilege)"
                                    ),
                                    {"role": role_name, "table": qualified, "privilege": privilege},
                                )
                                if result.scalar_one():
                                    raise ConfigurationError(
                                        "Ordinary Governance mutation remains available"
                                    )
                    for privilege in ("DELETE", "TRUNCATE"):
                        result = await connection.execute(
                            text("SELECT has_table_privilege(:role, :table, :privilege)"),
                            {"role": GOVERNANCE_ROLE, "table": qualified, "privilege": privilege},
                        )
                        if result.scalar_one():
                            raise ConfigurationError("Protected database grants are unsafe")
                    if schema != "platform_gov":
                        result = await connection.execute(
                            text("SELECT has_table_privilege(:role, :table, 'UPDATE')"),
                            {"role": GOVERNANCE_ROLE, "table": qualified},
                        )
                        if result.scalar_one():
                            raise ConfigurationError("Protected database grants are unsafe")
                    for privilege in ("SELECT", "INSERT"):
                        result = await connection.execute(
                            text("SELECT has_table_privilege(:role, :table, :privilege)"),
                            {"role": GOVERNANCE_ROLE, "table": qualified, "privilege": privilege},
                        )
                        if not result.scalar_one():
                            raise ConfigurationError("Protected database grants are unavailable")
                    if schema == "platform_gov":
                        result = await connection.execute(
                            text("SELECT has_table_privilege(:role, :table, 'UPDATE')"),
                            {"role": GOVERNANCE_ROLE, "table": qualified},
                        )
                        if not result.scalar_one():
                            raise ConfigurationError("Protected database grants are unavailable")
                extra = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_class AS c "
                        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r', 'p', 'v', 'm') "
                        "AND has_table_privilege(:role, c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE') "
                        "AND (n.nspname, c.relname) NOT IN "
                        "(('platform_gov','retention_policies'),('platform_gov','legal_holds'),"
                        "('platform_audit','audit_logs'),('eventing','outbox_messages')) "
                        "LIMIT 1"
                    ),
                    {"role": GOVERNANCE_ROLE},
                )
                if extra.first() is not None:
                    raise ConfigurationError("Protected database grants are unsafe")
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
        gate: ContributionGate,
    ) -> None:
        self._database_name = database_name
        self._pool_size = pool_size
        self._pool_timeout = pool_timeout
        self._gate = gate
        self._endpoint = None
        if governance_url is not None:
            parsed = make_url(governance_url)
            if any(
                key in parsed.query for key in ("host", "hostaddr", "port", "service", "options")
            ):
                raise ConfigurationError("Protected database endpoint is ambiguous")
            self._endpoint = (parsed.host, parsed.port, parsed.database)
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
    def requires_protected(
        cls, registered: _ProtectedCommandRegistration, command_type: type[Command]
    ) -> bool:
        return cls._protected_command(registered.owner, command_type)

    def record_registration(
        self,
        registered: _ProtectedCommandRegistration,
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
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command],
        tenant: TenantContext | None,
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
            if not self._gate.is_active(registration.generation):
                raise NotFoundError("Module contribution is not active")
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
        replacement: _GovernancePool | None = None
        try:
            try:
                parsed = make_url(url)
            except Exception:
                raise ConfigurationError("Protected database endpoint mismatch") from None
            if (
                self._endpoint is None
                or (parsed.host, parsed.port, parsed.database) != self._endpoint
                or any(
                    key in parsed.query
                    for key in ("host", "hostaddr", "port", "service", "options")
                )
            ):
                raise ConfigurationError("Protected database endpoint mismatch")
            replacement = _GovernancePool(
                url,
                size=self._pool_size,
                timeout=self._pool_timeout,
                database_name=self._database_name,
            )
            await replacement.validate()
        except BaseException:
            if replacement is not None:
                await replacement.close()
            async with self._lock:
                old = self._active
                self._active = None
            if old is not None and self._leases.get(old, 0) == 0:
                await old.close()
            raise
        assert replacement is not None
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
