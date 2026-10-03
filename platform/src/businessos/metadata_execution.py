"""Private ADR-022 execution enrollment for the ADR-023 Metadata foundation."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from businessos.context import TenantContext
from businessos.database_execution import (
    ProtectedDatabaseExecutionAuthority,
    _GovernancePool,  # pyright: ignore[reportPrivateUsage] -- private kernel composition reuse
    _normalized_policy,  # pyright: ignore[reportPrivateUsage] -- identical policy normalization
)
from businessos.errors import ConfigurationError
from businessos.persistence.uow import SQLAlchemyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from businessos.messages import Command, Query

METADATA_ROLE = "businessos_metadata"
_TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = {
    "platform_metadata.module_fence": {"SELECT", "INSERT", "UPDATE"},
    "platform_metadata.contract_fence": {"SELECT"},
    "platform_metadata.definitions": {"SELECT", "INSERT", "UPDATE"},
    "platform_metadata.revisions": {"SELECT", "INSERT"},
    "platform_metadata.revision_module_bindings": {"SELECT", "INSERT"},
    "platform_audit.audit_logs": {"SELECT", "INSERT"},
    "eventing.outbox_messages": {"SELECT", "INSERT"},
}
_HANDLERS = frozenset(
    {
        "CreateDefinition",
        "EditDraft",
        "PublishDefinition",
        "ReactivateRevision",
        "RetireDefinition",
        "ReadDraft",
        "ReadActiveRevision",
        "PreflightPublication",
    }
)


class _MetadataPool(_GovernancePool):
    async def validate(self) -> None:
        try:
            async with self.engine.connect() as connection:
                identity = await connection.execute(
                    text("SELECT current_database(), current_user, session_user")
                )
                if identity.one() != (self.database_name, METADATA_ROLE, METADATA_ROLE):
                    raise ConfigurationError("Metadata database identity mismatch")
                role = await connection.execute(
                    text(
                        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                        "rolbypassrls, rolreplication FROM pg_roles WHERE "
                        "rolname = 'businessos_metadata'"
                    )
                )
                if role.one_or_none() != (True, False, False, False, False, False, False):
                    raise ConfigurationError("Metadata database role is unsafe")
                unsafe = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
                        "JOIN pg_roles u ON u.oid=m.member WHERE r.rolname='businessos_metadata' "
                        "OR u.rolname='businessos_metadata' OR "
                        "(u.rolname IN ('businessos_app','businessos_worker') AND NOT "
                        "(u.rolname='businessos_worker' AND r.rolname='businessos_app')) "
                        "UNION ALL SELECT 1 FROM pg_class WHERE relowner=current_user::regrole "
                        "UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=current_user::regrole "
                        "UNION ALL SELECT 1 FROM pg_proc WHERE proowner=current_user::regrole "
                        "UNION ALL SELECT 1 FROM pg_database WHERE "
                        "datdba=current_user::regrole LIMIT 1"
                    )
                )
                if unsafe.first() is not None:
                    raise ConfigurationError("Metadata database ownership or membership is unsafe")
                creation = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                        "AND nspname <> 'information_schema' "
                        "AND has_schema_privilege(current_user,oid,'CREATE') LIMIT 1"
                    )
                )
                if creation.first() is not None:
                    raise ConfigurationError("Metadata role must not create schema objects")
                inventory = await connection.execute(
                    text(
                        "SELECT n.nspname || '.' || c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE c.relkind IN ('r','p','v','m','f') "
                        "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' AND ("
                        "has_table_privilege(current_user,c.oid,"
                        "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR "
                        "has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))"
                    )
                )
                if set(inventory.scalars()) != set(_TABLES):
                    raise ConfigurationError("Metadata database grant inventory is unsafe")
                for qualified, allowed in _TABLES.items():
                    for privilege in (
                        "SELECT",
                        "INSERT",
                        "UPDATE",
                        "DELETE",
                        "TRUNCATE",
                        "REFERENCES",
                        "TRIGGER",
                    ):
                        result = await connection.execute(
                            text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                            {"table": qualified, "privilege": privilege},
                        )
                        if result.scalar_one() != (privilege in allowed):
                            raise ConfigurationError("Metadata database grants are unsafe")
                        if (
                            privilege in {"SELECT", "INSERT", "UPDATE", "REFERENCES"}
                            and privilege not in allowed
                        ):
                            if (
                                qualified == "platform_metadata.contract_fence"
                                and privilege == "UPDATE"
                            ):
                                continue
                            columns_allowed = await connection.execute(
                                text(
                                    "SELECT has_any_column_privilege("
                                    "current_user,:table,:privilege)"
                                ),
                                {"table": qualified, "privilege": privilege},
                            )
                            if columns_allowed.scalar_one():
                                raise ConfigurationError("Metadata column grants are unsafe")
                    if qualified.startswith("platform_metadata."):
                        for ordinary in ("businessos_app", "businessos_worker"):
                            result = await connection.execute(
                                text(
                                    "SELECT has_table_privilege(:role, :table, "
                                    "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
                                    "OR "
                                    "has_any_column_privilege(:role,:table,'SELECT,INSERT,UPDATE')"
                                ),
                                {"role": ordinary, "table": qualified},
                            )
                            if result.scalar_one():
                                raise ConfigurationError(
                                    "Ordinary Metadata access remains available"
                                )
                    schema, table = qualified.split(".")
                    if table in {"module_fence", "contract_fence"}:
                        continue
                    state = await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                            "WHERE oid=to_regclass(:table)"
                        ),
                        {"table": qualified},
                    )
                    if state.one_or_none() != (True, True):
                        raise ConfigurationError("Metadata execution requires forced tenant RLS")
                    policies = await connection.execute(
                        text(
                            "SELECT roles,cmd,qual,with_check FROM pg_policies "
                            "WHERE schemaname=:schema AND tablename=:table "
                            "AND (roles @> ARRAY['public']::name[] "
                            "OR roles @> ARRAY['businessos_metadata']::name[])"
                        ),
                        {"schema": schema, "table": table},
                    )
                    rows = policies.all()
                    if (
                        len(rows) != 1
                        or rows[0][:2] != ([METADATA_ROLE], "ALL")
                        or any(
                            _normalized_policy(value) != _normalized_policy(_TENANT)
                            for value in rows[0][2:]
                        )
                    ):
                        raise ConfigurationError("Metadata tenant policy is unsafe")
                columns = await connection.execute(
                    text(
                        "SELECT a.attname FROM pg_attribute a WHERE a.attrelid="
                        "'platform_metadata.contract_fence'::regclass AND a.attnum>0 "
                        "AND NOT a.attisdropped AND has_column_privilege(current_user, "
                        "a.attrelid,a.attname,'UPDATE') ORDER BY a.attname"
                    )
                )
                if columns.scalars().all() != ["id"]:
                    raise ConfigurationError("Metadata contract generation grants are unsafe")
                # Ordinary sessions cannot invoke a SECURITY DEFINER escape hatch
                # or reach a protected relation through a transitive view.
                indirect = await connection.execute(
                    text(
                        "WITH RECURSIVE exposed(oid) AS (SELECT oid FROM pg_class WHERE "
                        "relnamespace='platform_metadata'::regnamespace UNION SELECT rw.ev_class "
                        "FROM exposed e JOIN pg_depend d ON d.refobjid=e.oid "
                        "AND d.refclassid='pg_class'::regclass JOIN pg_rewrite rw "
                        "ON rw.oid=d.objid AND d.classid='pg_rewrite'::regclass) "
                        "SELECT 1 FROM exposed e WHERE has_table_privilege('businessos_app',e.oid,"
                        "'SELECT,INSERT,UPDATE,DELETE') OR has_table_privilege('businessos_worker',"
                        "e.oid,'SELECT,INSERT,UPDATE,DELETE') OR "
                        "has_any_column_privilege('businessos_app',e.oid,'SELECT,INSERT,UPDATE') "
                        "OR "
                        "has_any_column_privilege('businessos_worker',e.oid,"
                        "'SELECT,INSERT,UPDATE') "
                        "UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid=p.pronamespace "
                        "WHERE p.prosecdef AND n.nspname NOT IN "
                        "('pg_catalog','information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' AND NOT (n.nspname='platform_identity' "
                        "AND p.proname='admit_workload' AND p.proargtypes='2950 "
                        "2950 20 25 25'::oidvector) "
                        "AND (has_function_privilege('businessos_app',p.oid,'EXECUTE') OR "
                        "has_function_privilege('businessos_worker',p.oid,'EXECUTE')) LIMIT 1"
                    )
                )
                if indirect.first() is not None:
                    raise ConfigurationError("Indirect ordinary Metadata access remains available")
                indirect_mutation = await connection.execute(
                    text(
                        "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "JOIN pg_proc p ON p.oid=t.tgfoid WHERE NOT t.tgisinternal "
                        "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' "
                        "AND t.tgenabled <> 'D' AND p.prosecdef AND ("
                        "has_table_privilege('businessos_app',c.oid,'INSERT,UPDATE,DELETE') OR "
                        "has_table_privilege('businessos_worker',c.oid,'INSERT,UPDATE,DELETE') OR "
                        "has_any_column_privilege('businessos_app',c.oid,'INSERT,UPDATE') OR "
                        "has_any_column_privilege('businessos_worker',c.oid,'INSERT,UPDATE')) "
                        "UNION ALL SELECT 1 FROM pg_rewrite rw JOIN pg_class c "
                        "ON c.oid=rw.ev_class "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' "
                        "AND rw.rulename <> '_RETURN' AND rw.ev_enabled <> 'D' AND ("
                        "has_table_privilege('businessos_app',c.oid,'INSERT,UPDATE,DELETE') OR "
                        "has_table_privilege('businessos_worker',c.oid,'INSERT,UPDATE,DELETE') OR "
                        "has_any_column_privilege('businessos_app',c.oid,'INSERT,UPDATE') OR "
                        "has_any_column_privilege('businessos_worker',c.oid,"
                        "'INSERT,UPDATE')) LIMIT 1"
                    )
                )
                if indirect_mutation.first() is not None:
                    raise ConfigurationError("Indirect Metadata mutation remains available")
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("Metadata database profile unavailable") from None

    def for_tenant(self, tenant: TenantContext) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            self.sessions, tenant, expected_database=self.database_name, expected_user=METADATA_ROLE
        )

    def installation(self) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(
            self.sessions, None, expected_database=self.database_name, expected_user=METADATA_ROLE
        )


class MetadataDatabaseExecutionAuthority(ProtectedDatabaseExecutionAuthority):
    _pool_type = _MetadataPool
    _profile = "foundation.metadata"

    @staticmethod
    def _protected_command(owner: str, command_type: type[Command | Query]) -> bool:
        return (
            owner == "foundation.metadata"
            and command_type.__module__ == "businessos_metadata.module"
            and command_type.__name__ in _HANDLERS
        )

    @asynccontextmanager
    async def internal_schema_read(self, tenant: TenantContext) -> AsyncGenerator[UnitOfWork]:
        """Private tenant-bound READ ONLY composition; never registered in module DI.

        PostgreSQL enforces read-only from transaction BEGIN, before identity/RLS setup.
        The Metadata-owned public reader returns only immutable schema facts.
        """
        async with self._lock:
            pool = self._active
            if not isinstance(pool, _MetadataPool) or self._closed:
                raise ConfigurationError("Metadata database profile unavailable")
            try:
                await pool.validate()
            except Exception:
                self._active = None
                if self._leases.get(pool, 0) == 0:
                    await pool.close()
                raise
            self._leases[pool] = self._leases.get(pool, 0) + 1
        try:
            sessions = async_sessionmaker(
                pool.engine.execution_options(postgresql_readonly=True), expire_on_commit=False
            )
            async with SQLAlchemyUnitOfWork(
                sessions, tenant, expected_database=pool.database_name, expected_user=METADATA_ROLE
            ) as unit:
                yield unit
        finally:
            async with self._lock:
                self._leases[pool] -= 1
                last = self._leases[pool] == 0
                if last:
                    del self._leases[pool]
            if last and pool is not self._active:
                await pool.close()

    @asynccontextmanager
    async def internal_installation(self) -> AsyncGenerator[UnitOfWork]:
        """Only trusted composition receives this lifecycle callback, never SDK/DI."""
        async with self._lock:
            pool = self._active
            if not isinstance(pool, _MetadataPool) or self._closed:
                raise ConfigurationError("Metadata database profile unavailable")
            try:
                await pool.validate()
            except Exception:
                self._active = None
                if self._leases.get(pool, 0) == 0:
                    await pool.close()
                raise
            self._leases[pool] = self._leases.get(pool, 0) + 1
        try:
            async with pool.installation() as unit:
                yield unit
        finally:
            async with self._lock:
                self._leases[pool] -= 1
                last = self._leases[pool] == 0
                if last:
                    del self._leases[pool]
            if last and pool is not self._active:
                await pool.close()
