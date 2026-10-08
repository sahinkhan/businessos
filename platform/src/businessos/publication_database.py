"""Kernel-private ADR-024 database profile; never a dispatcher handler UOW."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, ClassVar
from weakref import WeakKeyDictionary

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as PoolTimeout

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import TenantContext
from businessos.database_execution import (
    _ProtectedCommandRegistration,  # pyright: ignore[reportPrivateUsage] -- exact enrollment
)
from businessos.errors import ConfigurationError, NotFoundError, ProtectedDatabaseCapacityError
from businessos.metadata_execution import (
    MetadataDatabaseExecutionAuthority,
    _MetadataPool,  # pyright: ignore[reportPrivateUsage] -- kernel-private pool validation
)
from businessos.persistence.uow import SQLAlchemyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from businessos.messages import Command, Query


_logger = logging.getLogger("businessos.audit.protected-database")


class _PublicationPool(_MetadataPool):
    @staticmethod
    def _connect_options(timeout: float) -> dict[str, object]:
        return {
            "connect_timeout": max(1, ceil(timeout)),
            "options": "-c statement_timeout=30000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=30000 -c transaction_timeout=60000",
        }

    _role = "businessos_ui_publication"
    _tables: ClassVar[dict[str, set[str]]] = {
        "platform_metadata.module_fence": {"SELECT"},
        "platform_metadata.contract_fence": {"SELECT"},
        "platform_metadata.ui_installation_lineage": {"SELECT"},
        "platform_metadata.ui_overlays": {"SELECT", "INSERT", "UPDATE"},
        "platform_metadata.ui_overlay_revisions": {"SELECT", "INSERT"},
        "platform_metadata.ui_revision_module_bindings": {"SELECT", "INSERT"},
        "platform_metadata.ui_revision_binding_seals": {"SELECT", "INSERT"},
        "platform_metadata.ui_expected_provenance": {"SELECT", "INSERT"},
        "platform_metadata.ui_expected_members": {"SELECT", "INSERT"},
        "platform_audit.audit_logs": {"SELECT", "INSERT"},
        "eventing.outbox_messages": {"SELECT", "INSERT"},
    }
    _column_grants: ClassVar[dict[str, dict[str, set[str]]]] = {
        "platform_metadata.contract_fence": {"UPDATE": {"id"}},
        "platform_metadata.module_fence": {
            "UPDATE": {"module_id", "artifact_identity", "generation"},
            "INSERT": {"module_id", "artifact_identity", "generation"},
        },
    }

    async def validate(self) -> None:
        await super().validate()
        async with self.engine.connect() as connection:
            version = await connection.execute(
                text(
                    "SELECT 1 FROM pg_constraint WHERE conrelid="
                    "to_regclass('platform_metadata.ui_expected_provenance') "
                    "AND conname='ui_expected_provenance_model_version_check' "
                    "AND pg_get_constraintdef(oid)='CHECK ((model_version = 1))' AND convalidated"
                )
            )
            if version.scalar_one_or_none() != 1:
                raise ConfigurationError("UI publication provenance schema unavailable")
            lineage = await connection.execute(
                text(
                    "SELECT count(*) FROM platform_metadata.ui_installation_lineage "
                    "WHERE singleton=1"
                )
            )
            if lineage.scalar_one() != 1:
                raise ConfigurationError("UI publication installation lineage unavailable")
            triggers = await connection.execute(
                text(
                    "SELECT c.relname,t.tgname,t.tgenabled FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE c.relnamespace='platform_metadata'::regnamespace AND NOT t.tgisinternal"
                )
            )
            actual = {(table, name) for table, name, enabled in triggers if enabled == "O"}
            required = {
                ("ui_expected_provenance", "check_ui_expected_header"),
                ("ui_expected_provenance", "immutable_ui_expected_provenance"),
                ("ui_expected_provenance", "require_expected_ui_seal"),
                ("ui_expected_members", "check_ui_expected_member"),
                ("ui_expected_members", "immutable_ui_expected_members"),
                ("ui_revision_binding_seals", "check_ui_binding_seal"),
                ("ui_revision_binding_seals", "immutable_ui_binding_seal"),
                ("ui_overlay_revisions", "require_ui_binding_seal"),
                ("ui_overlays", "require_active_ui_binding_seal"),
                ("ui_overlays", "ui_active_bindings"),
                ("module_fence", "check_module_identity"),
            }
            if not required <= actual:
                raise ConfigurationError("UI publication verifier is unavailable")
            unsafe = await connection.execute(
                text(
                    "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema') "
                    "AND n.nspname NOT LIKE 'pg_%' AND "
                    "has_function_privilege('businessos_metadata',p.oid,'EXECUTE') "
                    "UNION ALL SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
                    "JOIN pg_roles u ON u.oid=m.member WHERE "
                    "(r.rolname='businessos_metadata_fence_owner' AND "
                    "u.rolname<>'businessos_migrator') "
                    "OR u.rolname='businessos_metadata_fence_owner' LIMIT 1"
                )
            )
            if unsafe.first() is not None:
                raise ConfigurationError("Indirect Metadata publication authority is unsafe")
            indirect = await connection.execute(
                text("""
                WITH RECURSIVE exposed(oid) AS (
                  SELECT oid FROM pg_class WHERE oid IN (
                    'platform_metadata.ui_expected_provenance'::regclass,
                    'platform_metadata.ui_expected_members'::regclass,
                    'platform_metadata.ui_installation_lineage'::regclass)
                  UNION SELECT rw.ev_class FROM exposed e JOIN pg_depend d
                    ON d.refobjid=e.oid AND d.refclassid='pg_class'::regclass
                    JOIN pg_rewrite rw ON rw.oid=d.objid
                    AND d.classid='pg_rewrite'::regclass)
                SELECT 1 FROM exposed e WHERE
                  has_table_privilege('businessos_metadata',e.oid,'INSERT,UPDATE,DELETE')
                  OR has_any_column_privilege('businessos_metadata',e.oid,'INSERT,UPDATE')
                UNION ALL SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
                  JOIN pg_class c ON c.oid=t.tgrelid
                  WHERE NOT t.tgisinternal AND t.tgenabled<>'D' AND p.prosecdef
                    AND (has_table_privilege('businessos_metadata',c.oid,'INSERT,UPDATE,DELETE')
                      OR has_any_column_privilege('businessos_metadata',c.oid,'INSERT,UPDATE'))
                    AND NOT (
                      (c.oid='platform_metadata.definitions'::regclass AND
                       p.oid='platform_metadata.adjust_active_bindings()'::regprocedure)
                      OR (c.oid='platform_metadata.ui_overlays'::regclass AND
                       p.oid='platform_metadata.adjust_ui_active_bindings()'::regprocedure))
                UNION ALL SELECT 1 FROM pg_default_acl d,
                  LATERAL aclexplode(d.defaclacl) a
                  WHERE (a.grantee=0 OR a.grantee IN (
                    'businessos_metadata'::regrole,'businessos_ui_publication'::regrole))
                    AND d.defaclobjtype IN ('r','S')
                    AND a.privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE','TRIGGER')
                LIMIT 1
            """)
            )
            if indirect.first() is not None:
                raise ConfigurationError("Indirect completeness write path is unsafe")
            counter_role = await connection.execute(
                text(
                    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolbypassrls,"
                    "rolreplication FROM pg_roles WHERE rolname='businessos_metadata_fence_owner'"
                )
            )
            if counter_role.one_or_none() != (False, False, False, False, False, False, False):
                raise ConfigurationError("Metadata counter owner must remain a safe NOLOGIN role")
            for table in (
                "ui_expected_provenance",
                "ui_expected_members",
                "ui_installation_lineage",
            ):
                grant = await connection.execute(
                    text(
                        "SELECT has_table_privilege('businessos_metadata',:table,"
                        "'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER') OR "
                        "has_any_column_privilege('businessos_metadata',:table,'INSERT,UPDATE')"
                    ),
                    {"table": "platform_metadata." + table},
                )
                if grant.scalar_one():
                    raise ConfigurationError(
                        "Ordinary Metadata may not issue completeness provenance"
                    )
            owners = await connection.execute(
                text(
                    "SELECT p.proname,p.prosecdef,r.rolname,p.proconfig FROM pg_proc p "
                    "JOIN pg_roles r ON r.oid=p.proowner WHERE "
                    "p.pronamespace='platform_metadata'::regnamespace AND p.proname IN "
                    "('adjust_active_bindings','adjust_ui_active_bindings')"
                )
            )
            states = owners.all()
            if len(states) != 2 or any(
                not secured
                or owner != "businessos_metadata_fence_owner"
                or config != ["search_path=pg_catalog, pg_temp"]
                for _, secured, owner, config in states
            ):
                raise ConfigurationError("Metadata counter transition ownership is unsafe")


class PublicationDatabaseAuthority(MetadataDatabaseExecutionAuthority):
    """Enrollment/pool mechanics reused; invocation belongs exclusively to executor."""

    _pool_type = _PublicationPool
    _profile = "foundation.metadata.ui-publication.v1"

    def __init__(
        self,
        *,
        governance_url: str | None,
        database_name: str,
        pool_size: int,
        pool_timeout: float,
        gate: ContributionGate,
    ) -> None:
        super().__init__(
            governance_url=governance_url,
            database_name=database_name,
            pool_size=pool_size,
            pool_timeout=pool_timeout,
            gate=gate,
        )
        # A retired pool has one owned disposal, even when close/rotation and
        # the final admission/transaction lease converge concurrently.
        self._disposals: WeakKeyDictionary[_PublicationPool, asyncio.Task[None]] = (
            WeakKeyDictionary()
        )

    @staticmethod
    def _protected_command(owner: str, command_type: type[Command | Query]) -> bool:
        return (
            owner == "foundation.metadata"
            and command_type.__module__ == "businessos_metadata.module"
            and command_type.__name__
            in {"PublishUIOverlay", "ReactivateUIOverlay", "RetireUIOverlay"}
        )

    def _registration_generation(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
    ) -> ContributionGeneration:
        registration = self._registrations.get(id(registered))
        if (
            not self.requires_protected(registered, command_type)
            or registration is None
            or registration.registered is not registered
            or registration.command_type is not command_type
            or registration.generation is not registered.generation
        ):
            raise PermissionError("Publication requires exact trusted registration")
        if not self._gate.is_active(registration.generation):
            raise NotFoundError("Module contribution is not active")
        return registration.generation

    def _dispose_unleased(self, pool: _PublicationPool) -> asyncio.Task[None] | None:
        """Called only in the state critical section; disposal runs outside it."""
        if self._leases.get(pool, 0):
            return None
        task = self._disposals.get(pool)
        if task is None:
            task = asyncio.create_task(pool.close(), name="businessos-publication-pool-disposal")
            self._disposals[pool] = task
        return task

    async def _release(self, lease: _PublicationLease, *, revoke: bool) -> None:
        disposal: asyncio.Task[None] | None
        async with self._lock:
            if lease.released:
                return
            lease.released = True
            pool = lease.pool
            if revoke and self._active is pool:
                self._active = None
            count = self._leases[pool] - 1
            if count:
                self._leases[pool] = count
            else:
                del self._leases[pool]
            disposal = self._dispose_unleased(pool) if pool is not self._active else None
        if disposal is not None:
            await disposal

    @asynccontextmanager
    async def _admitted_pool(
        self,
        registered: _ProtectedCommandRegistration | None = None,
        command_type: type[Command | Query] | None = None,
    ) -> AsyncGenerator[tuple[_PublicationPool, float]]:
        # One absolute deadline includes state-lock wait, both profile validation
        # checkouts, state revalidation, and the actual publication UOW checkout.
        deadline = asyncio.get_running_loop().time() + self._pool_timeout
        lease: _PublicationLease | None = None
        revoke = False
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    async with self._lock:
                        if registered is not None and command_type is not None:
                            self._registration_generation(registered, command_type)
                        pool = self._active
                        if not isinstance(pool, _PublicationPool) or self._closed:
                            raise ConfigurationError("Protected database profile unavailable")
                        # Reserve before releasing the mutex: a rotating/closing
                        # authority cannot dispose validation's selected engine.
                        lease = _PublicationLease(pool)
                        self._leases[pool] = self._leases.get(pool, 0) + 1
                    try:
                        await pool.validate()
                    except (ProtectedDatabaseCapacityError, PoolTimeout):
                        raise
                    except Exception:
                        revoke = True
                        raise
                    async with self._lock:
                        if registered is not None and command_type is not None:
                            self._registration_generation(registered, command_type)
                        if self._closed or self._active is not pool:
                            # Zero automatic retries. The caller may submit a new
                            # command with fresh authority after a cutover.
                            raise ConfigurationError("Publication profile changed during admission")
            except (TimeoutError, PoolTimeout):
                raise ProtectedDatabaseCapacityError() from None
            yield pool, deadline
        finally:
            if lease is not None:
                await _finish_owned(self._release(lease, revoke=revoke))

    @asynccontextmanager
    async def for_command(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
        tenant: TenantContext | None,
    ) -> AsyncGenerator[UnitOfWork]:
        if tenant is None:
            raise PermissionError("Trusted tenant required")
        generation = self._registration_generation(registered, command_type)
        async with self._admitted_pool(registered, command_type) as (pool, deadline):
            _logger.info(
                "Protected database execution selected",
                extra={
                    "protected_database_profile": self._profile,
                    "handler_generation_owner": generation.owner,
                    "handler_generation_number": generation.number,
                },
            )
            try:
                yield _PublicationUnitOfWork(pool, tenant, deadline)
            except PoolTimeout:
                raise ProtectedDatabaseCapacityError() from None

    async def validate(self) -> None:
        async with self._admitted_pool():
            pass

    @asynccontextmanager
    async def internal_installation(self) -> AsyncGenerator[UnitOfWork]:
        # Lifecycle admission uses the same short critical sections and lease
        # finalizer; it cannot queue command callers behind blocking validation.
        async with self._admitted_pool() as (pool, deadline):
            async with _PublicationUnitOfWork(pool, None, deadline) as unit:
                yield unit

    async def _cutover(
        self, replacement: _PublicationPool | None, *, expected: _PublicationPool | None = None
    ) -> None:
        disposals: list[asyncio.Task[None]] = []
        closed = False
        async with self._lock:
            if expected is not None and self._active is not expected:
                # A failed older rotation must not revoke a newer validated pool.
                pass
            elif self._closed and replacement is not None:
                closed = True
            else:
                old = self._active
                self._active = replacement
                if isinstance(old, _PublicationPool):
                    task = self._dispose_unleased(old)
                    if task is not None:
                        disposals.append(task)
            if replacement is not None and replacement is not self._active:
                task = self._dispose_unleased(replacement)
                if task is not None:
                    disposals.append(task)
        for task in disposals:
            await task
        if closed:
            raise ConfigurationError("Protected database profile is closed")

    async def rotate(self, url: str) -> None:
        replacement: _PublicationPool | None = None
        async with self._lock:
            selected = self._active
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
            replacement = self._pool_type(
                url,
                size=self._pool_size,
                timeout=self._pool_timeout,
                database_name=self._database_name,
            )
            async with asyncio.timeout(self._pool_timeout):
                await replacement.validate()
        except BaseException:
            await _finish_owned(self._rotation_failed(replacement, selected))
            raise
        await _finish_owned(self._cutover(replacement))

    async def _rotation_failed(
        self, replacement: _PublicationPool | None, selected: object | None
    ) -> None:
        # Disposal and admission revocation share one cleanup owner. Repeated
        # cancellation during failed-replacement disposal cannot skip revocation.
        try:
            if replacement is not None:
                await self._discard_replacement(replacement)
        finally:
            if isinstance(selected, _PublicationPool):
                await self._cutover(None, expected=selected)

    async def _discard_replacement(self, pool: _PublicationPool) -> None:
        async with self._lock:
            task = self._dispose_unleased(pool)
        if task is not None:
            await task

    async def close(self) -> None:
        await _finish_owned(self._close())

    async def _close(self) -> None:
        async with self._lock:
            self._closed = True
        await self._cutover(None)


@dataclass(slots=True)
class _PublicationLease:
    pool: _PublicationPool
    released: bool = False


class _PublicationUnitOfWork(SQLAlchemyUnitOfWork):
    def __init__(
        self, pool: _PublicationPool, tenant: TenantContext | None, deadline: float
    ) -> None:
        super().__init__(
            pool.sessions,
            tenant,
            expected_database=pool.database_name,
            expected_user="businessos_ui_publication",
        )
        self._admission_deadline = deadline

    async def __aenter__(self) -> _PublicationUnitOfWork:
        try:
            async with asyncio.timeout_at(self._admission_deadline):
                await super().__aenter__()
        except (TimeoutError, PoolTimeout):
            raise ProtectedDatabaseCapacityError() from None
        return self


async def _finish_owned[CleanupResult](
    operation: Coroutine[object, object, CleanupResult],
) -> CleanupResult:
    """Join one owned cleanup despite repeated cancellation, as UOW cleanup does."""
    cleanup = asyncio.create_task(operation, name="businessos-publication-authority-cleanup")
    cancellation: asyncio.CancelledError | None = None
    current = asyncio.current_task()
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            cancellation = cancellation or error
            if current is not None:
                while current.cancelling():
                    current.uncancel()
    result = cleanup.result()
    if cancellation is not None:
        raise cancellation
    return result
