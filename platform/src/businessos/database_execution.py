"""Protected, exact-registration database execution authority (ADR-022)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import TenantContext
from businessos.dependency_entitlement import internal_valid_restricted_dependency_entitlement
from businessos.errors import ConfigurationError, NotFoundError, ProtectedDatabaseCapacityError
from businessos.persistence.uow import SQLAlchemyUnitOfWork, UnitOfWork

if TYPE_CHECKING:
    from businessos.messages import Command, Query


GOVERNANCE_PROFILE = "foundation.data_governance"
GOVERNANCE_ROLE = "businessos_governance"
_logger = logging.getLogger("businessos.audit.protected-database")
# This security evidence must survive an installation's diagnostic log level.
_logger.setLevel(logging.INFO)
_GOVERNANCE_COMMANDS = frozenset(
    {
        "CreateRetentionPolicyCommand",
        "CreateRetentionPolicyV2Command",
        "PlaceLegalHoldCommand",
        "ReleaseLegalHoldCommand",
        "SetRetentionPolicyV2",
        "ReplaceRetentionPolicyV2",
        "PlaceRetentionHoldV2",
        "ReleaseRetentionHoldV2",
        "ExecuteDestructiveLifecycleV2",
        "RecordDestructiveCleanupResultV2",
    }
)
_GOVERNANCE_COMMAND_MODULES = frozenset(
    {"businessos_data_governance.module", "businessos_data_governance.retention_v2"}
)
_TENANT_POLICY = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


@dataclass(frozen=True, slots=True)
class _ParticipatingOwnerRelation:
    """Private, reviewed enrollment for one protected command's owner write."""

    command: str
    relation: str
    policy: str
    protected_update_columns: frozenset[str]
    ordinary_insert_columns: frozenset[str]
    ordinary_update_columns: frozenset[str]


_PARTICIPATING_OWNER_RELATIONS = (
    _ParticipatingOwnerRelation(
        command="ExecuteDestructiveLifecycleV2",
        relation="mod_example_phase1_proof.proof_records",
        policy="proof_records_governance_tenant",
        protected_update_columns=frozenset({"lifecycle", "value", "description"}),
        ordinary_insert_columns=frozenset({"id", "tenant_id", "command_id", "value"}),
        ordinary_update_columns=frozenset({"description"}),
    ),
)


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
    command_type: type[Command | Query]
    generation: ContributionGeneration


class DatabaseExecutionSelector(Protocol):
    def requires_protected(
        self, registered: _ProtectedCommandRegistration, command_type: type[Command | Query]
    ) -> bool: ...

    def record_registration(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
        entitlement: object,
    ) -> None: ...

    def remove_generation(self, generation: ContributionGeneration) -> None: ...

    def for_command(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
        tenant: TenantContext | None,
    ) -> AbstractAsyncContextManager[UnitOfWork]: ...


class ProtectedDatabaseProfiles:
    """Composition-owned enumerated profiles; never registered in module DI."""

    def __init__(self, *profiles: DatabaseExecutionSelector) -> None:
        self._profiles = profiles

    def requires_protected(
        self, registered: _ProtectedCommandRegistration, command_type: type[Command | Query]
    ) -> bool:
        return any(
            profile.requires_protected(registered, command_type) for profile in self._profiles
        )

    def record_registration(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
        entitlement: object,
    ) -> None:
        for profile in self._profiles:
            profile.record_registration(registered, command_type, entitlement)

    def remove_generation(self, generation: ContributionGeneration) -> None:
        for profile in self._profiles:
            profile.remove_generation(generation)

    @asynccontextmanager
    async def for_command(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
        tenant: TenantContext | None,
    ) -> AsyncGenerator[UnitOfWork]:
        matches = [p for p in self._profiles if p.requires_protected(registered, command_type)]
        if not matches:
            raise PermissionError("Handler has no protected database execution profile")
        if len(matches) != 1:
            raise ConfigurationError("Protected execution profile is missing or ambiguous")
        async with matches[0].for_command(registered, command_type, tenant) as unit:
            yield unit

    @asynccontextmanager
    async def for_message(
        self,
        registered: _ProtectedCommandRegistration,
        message: Command | Query,
        tenant: TenantContext | None,
    ) -> AsyncGenerator[UnitOfWork]:
        matches = [p for p in self._profiles if p.requires_protected(registered, type(message))]
        if len(matches) != 1:
            raise ConfigurationError("Protected execution profile is missing or ambiguous")
        profile = matches[0]
        admission = getattr(profile, "for_message", None)
        if admission is None:
            async with profile.for_command(registered, type(message), tenant) as unit:
                yield unit
        else:
            async with admission(registered, message, tenant) as unit:
                yield unit


class _GovernancePool:
    @staticmethod
    def _connect_options(timeout: float) -> dict[str, object]:
        return {}

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
            connect_args=self._connect_options(timeout),
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
                    (
                        "platform_gov",
                        "retention_policies_v2",
                        "retention_policies_v2_governance_tenant",
                    ),
                    ("platform_gov", "legal_holds_v2", "legal_holds_v2_governance_tenant"),
                    (
                        "platform_gov",
                        "destructive_decisions_v2",
                        "destructive_decisions_v2_governance_tenant",
                    ),
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
                        result = await connection.execute(
                            text("SELECT has_any_column_privilege(:role, :table, 'UPDATE')"),
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
                for table_name in (
                    "tenant_classifications",
                    "tenant_classification_versions",
                    "classification_overlays",
                    "classification_legacy_mappings",
                ):
                    state = await connection.execute(
                        text(
                            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class AS c "
                            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = 'platform_gov' AND c.relname = :table"
                        ),
                        {"table": table_name},
                    )
                    if state.one_or_none() != (True, True):
                        raise ConfigurationError("Protected database RLS is unsafe")
                    policies = await connection.execute(
                        text(
                            "SELECT policyname, roles, cmd, qual, with_check "
                            "FROM pg_policies WHERE schemaname = 'platform_gov' "
                            "AND tablename = :table AND (roles @> ARRAY['public']::name[] "
                            "OR roles @> ARRAY[:role]::name[])"
                        ),
                        {"table": table_name, "role": GOVERNANCE_ROLE},
                    )
                    classification_policies = {
                        name: (roles, command, _normalized_policy(qual), _normalized_policy(check))
                        for name, roles, command, qual, check in policies
                    }
                    if table_name == "classification_legacy_mappings":
                        expected = {
                            "classification_legacy_mappings_governance_read": (
                                [GOVERNANCE_ROLE],
                                "SELECT",
                                _normalized_policy(f"tenant_id IS NULL OR {_TENANT_POLICY}"),
                                "",
                            )
                        }
                    else:
                        expected = {
                            f"{table_name}_governance_tenant": (
                                [GOVERNANCE_ROLE],
                                "SELECT",
                                _normalized_policy(_TENANT_POLICY),
                                "",
                            ),
                            f"{table_name}_governance_lock": (
                                [GOVERNANCE_ROLE],
                                "UPDATE",
                                _normalized_policy(_TENANT_POLICY),
                                "false",
                            ),
                        }
                    if classification_policies != expected:
                        raise ConfigurationError("Protected database RLS policy is unsafe")
                for owner_relation in _PARTICIPATING_OWNER_RELATIONS:
                    if owner_relation.command not in _GOVERNANCE_COMMANDS:
                        raise ConfigurationError("Governed owner enrollment is unsafe")
                    proof_table = owner_relation.relation
                    proof_exists = await connection.execute(
                        text("SELECT to_regclass(:table)"), {"table": proof_table}
                    )
                    if proof_exists.scalar_one() is None:
                        continue
                    schema_name, table_name = proof_table.split(".", 1)
                    proof_state = await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                            "WHERE oid = CAST(:table AS regclass)"
                        ),
                        {"table": proof_table},
                    )
                    if proof_state.one() != (True, True):
                        raise ConfigurationError("Governed owner RLS is unsafe")
                    proof_policies = await connection.execute(
                        text(
                            "SELECT policyname, roles, cmd, qual, with_check "
                            "FROM pg_policies WHERE schemaname = :schema "
                            "AND tablename = :table "
                            "AND (roles @> ARRAY['public']::name[] "
                            "OR roles @> ARRAY[:role]::name[])"
                        ),
                        {"role": GOVERNANCE_ROLE, "schema": schema_name, "table": table_name},
                    )
                    owner_policies = proof_policies.all()
                    if (
                        len(owner_policies) != 1
                        or owner_policies[0][:3]
                        != (owner_relation.policy, [GOVERNANCE_ROLE], "ALL")
                        or any(
                            _normalized_policy(expression) != _normalized_policy(_TENANT_POLICY)
                            for expression in owner_policies[0][3:]
                        )
                    ):
                        raise ConfigurationError("Governed owner RLS policy is unsafe")
                    for role_name in ("businessos_app", "businessos_worker", GOVERNANCE_ROLE):
                        for privilege in ("DELETE", "TRUNCATE"):
                            grant = await connection.execute(
                                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                                {"role": role_name, "table": proof_table, "privilege": privilege},
                            )
                            if grant.scalar_one():
                                raise ConfigurationError("Governed owner grants are unsafe")
                    for privilege in ("INSERT", "UPDATE"):
                        grant = await connection.execute(
                            text("SELECT has_table_privilege(:role, :table, :privilege)"),
                            {"role": GOVERNANCE_ROLE, "table": proof_table, "privilege": privilege},
                        )
                        if grant.scalar_one():
                            raise ConfigurationError("Governed owner grants are unsafe")
                    columns = await connection.execute(
                        text(
                            "SELECT a.attname, "
                            "has_column_privilege(:role, c.oid, a.attname, 'INSERT'), "
                            "has_column_privilege(:role, c.oid, a.attname, 'UPDATE') "
                            "FROM pg_attribute AS a JOIN pg_class AS c ON c.oid = a.attrelid "
                            "WHERE c.oid = CAST(:table AS regclass) "
                            "AND a.attnum > 0 AND NOT a.attisdropped"
                        ),
                        {"role": GOVERNANCE_ROLE, "table": proof_table},
                    )
                    if any(
                        insert or update != (column in owner_relation.protected_update_columns)
                        for column, insert, update in columns
                    ):
                        raise ConfigurationError("Governed owner column grants are unsafe")
                    for role_name in ("businessos_app", "businessos_worker"):
                        ordinary_table = await connection.execute(
                            text(
                                "SELECT has_table_privilege(:role, :table, "
                                "'INSERT, UPDATE, DELETE, TRUNCATE')"
                            ),
                            {"role": role_name, "table": proof_table},
                        )
                        if ordinary_table.scalar_one():
                            raise ConfigurationError("Governed owner grants are unsafe")
                        ordinary_columns = await connection.execute(
                            text(
                                "SELECT a.attname, "
                                "has_column_privilege(:role, c.oid, a.attname, 'INSERT'), "
                                "has_column_privilege(:role, c.oid, a.attname, 'UPDATE') "
                                "FROM pg_attribute AS a JOIN pg_class AS c ON c.oid = a.attrelid "
                                "WHERE c.oid = CAST(:table AS regclass) "
                                "AND a.attnum > 0 AND NOT a.attisdropped"
                            ),
                            {"role": role_name, "table": proof_table},
                        )
                        if any(
                            (insert and column not in owner_relation.ordinary_insert_columns)
                            or (update and column not in owner_relation.ordinary_update_columns)
                            for column, insert, update in ordinary_columns
                        ):
                            raise ConfigurationError("Governed owner grants are unsafe")
                extra = await connection.execute(
                    text(
                        "SELECT n.nspname, c.relname FROM pg_class AS c "
                        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r', 'p', 'v', 'm') "
                        "AND (has_table_privilege(:role, c.oid, "
                        "'INSERT, UPDATE, DELETE, TRUNCATE') "
                        "OR has_any_column_privilege(:role, c.oid, 'INSERT, UPDATE')) "
                        "AND (n.nspname, c.relname) NOT IN "
                        "(('platform_gov','retention_policies'),('platform_gov','legal_holds'),"
                        "('platform_gov','retention_policies_v2'),"
                        "('platform_gov','legal_holds_v2'),"
                        "('platform_gov','destructive_decisions_v2'),"
                        "('mod_example_phase1_proof','proof_records'),"
                        "('platform_audit','audit_logs'),('eventing','outbox_messages'),"
                        "('platform_gov','tenant_classifications'),"
                        "('platform_gov','tenant_classification_versions'),"
                        "('platform_gov','classification_overlays')) "
                        "LIMIT 1"
                    ),
                    {"role": GOVERNANCE_ROLE},
                )
                if extra.first() is not None:
                    raise ConfigurationError("Protected database grants are unsafe")
                for table_name in (
                    "tenant_classifications",
                    "tenant_classification_versions",
                    "classification_overlays",
                ):
                    qualified = f"platform_gov.{table_name}"
                    table_dml = await connection.execute(
                        text(
                            "SELECT has_table_privilege(:role, :table, "
                            "'INSERT, UPDATE, DELETE, TRUNCATE')"
                        ),
                        {"role": GOVERNANCE_ROLE, "table": qualified},
                    )
                    columns = await connection.execute(
                        text(
                            "SELECT a.attname, "
                            "has_column_privilege(:role, c.oid, a.attname, 'INSERT'), "
                            "has_column_privilege(:role, c.oid, a.attname, 'UPDATE') "
                            "FROM pg_attribute AS a JOIN pg_class AS c ON c.oid = a.attrelid "
                            "WHERE c.oid = CAST(:table AS regclass) "
                            "AND a.attnum > 0 AND NOT a.attisdropped"
                        ),
                        {"role": GOVERNANCE_ROLE, "table": qualified},
                    )
                    if table_dml.scalar_one() or any(
                        insert or (update and column != "id") or (column == "id" and not update)
                        for column, insert, update in columns
                    ):
                        raise ConfigurationError("Protected database grants are unsafe")
                indirect = await connection.execute(
                    text(
                        "WITH RECURSIVE dependent_views(oid) AS ("
                        "SELECT unnest(ARRAY['platform_gov.retention_policies'::regclass, "
                        "'platform_gov.legal_holds'::regclass, "
                        "'platform_gov.retention_policies_v2'::regclass, "
                        "'platform_gov.legal_holds_v2'::regclass, "
                        "'platform_gov.destructive_decisions_v2'::regclass])::oid "
                        "UNION SELECT to_regclass(name)::oid "
                        "FROM unnest(CAST(:owner_relations AS text[])) AS name "
                        "UNION SELECT rw.ev_class FROM pg_rewrite AS rw "
                        "JOIN pg_depend AS dep ON dep.objid = rw.oid "
                        "JOIN dependent_views AS prior ON dep.refobjid = prior.oid "
                        "JOIN pg_class AS view ON view.oid = rw.ev_class "
                        "WHERE view.relkind IN ('v', 'm')) "
                        "SELECT 1 FROM dependent_views AS dependent "
                        "JOIN pg_class AS c ON c.oid = dependent.oid "
                        "WHERE c.relkind IN ('v', 'm') "
                        "AND (has_table_privilege('businessos_app', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_table_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_any_column_privilege('businessos_app', c.oid, 'INSERT, UPDATE') "
                        "OR has_any_column_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE')) "
                        "UNION ALL SELECT 1 FROM pg_proc AS p "
                        "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' AND p.prosecdef "
                        "AND NOT (n.nspname = 'platform_identity' "
                        "AND p.proname = 'admit_workload' AND p.pronargs = 5 "
                        "AND p.proargtypes[0] = 'uuid'::regtype "
                        "AND p.proargtypes[1] = 'uuid'::regtype "
                        "AND p.proargtypes[2] = 'bigint'::regtype "
                        "AND p.proargtypes[3] = 'text'::regtype "
                        "AND p.proargtypes[4] = 'text'::regtype) "
                        "AND (has_function_privilege('businessos_app', p.oid, 'EXECUTE') "
                        "OR has_function_privilege('businessos_worker', p.oid, 'EXECUTE')) "
                        "UNION ALL SELECT 1 FROM pg_trigger AS t "
                        "JOIN pg_class AS c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                        "JOIN pg_proc AS p ON p.oid = t.tgfoid "
                        "WHERE NOT t.tgisinternal AND t.tgenabled <> 'D' AND p.prosecdef "
                        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' "
                        "AND (has_table_privilege('businessos_app', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_table_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_any_column_privilege('businessos_app', c.oid, "
                        "'INSERT, UPDATE') "
                        "OR has_any_column_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE')) "
                        "UNION ALL SELECT 1 FROM pg_rewrite AS rw "
                        "JOIN pg_class AS c ON c.oid = rw.ev_class "
                        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                        "WHERE rw.rulename <> '_RETURN' AND rw.ev_enabled <> 'D' "
                        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                        "AND n.nspname NOT LIKE 'pg_%' "
                        "AND (has_table_privilege('businessos_app', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_table_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE, DELETE') "
                        "OR has_any_column_privilege('businessos_app', c.oid, "
                        "'INSERT, UPDATE') "
                        "OR has_any_column_privilege('businessos_worker', c.oid, "
                        "'INSERT, UPDATE')) "
                        "UNION ALL SELECT 1 FROM pg_default_acl AS d "
                        "LEFT JOIN pg_namespace AS n ON n.oid = d.defaclnamespace "
                        "CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a "
                        "WHERE (n.nspname = ANY(CAST(:owner_schemas AS text[])) "
                        "OR d.defaclnamespace = 0) "
                        "AND d.defaclobjtype = 'r' "
                        "AND a.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE') "
                        "AND (a.grantee = 0 OR a.grantee IN "
                        "(SELECT oid FROM pg_roles WHERE rolname IN "
                        "('businessos_app', 'businessos_worker', "
                        "'businessos_governance'))) LIMIT 1"
                    ),
                    {
                        "owner_relations": [
                            profile.relation for profile in _PARTICIPATING_OWNER_RELATIONS
                        ],
                        "owner_schemas": [
                            "platform_gov",
                            *(
                                profile.relation.split(".", 1)[0]
                                for profile in _PARTICIPATING_OWNER_RELATIONS
                            ),
                        ],
                    },
                )
                if indirect.first() is not None:
                    raise ConfigurationError(
                        "Indirect ordinary Governance mutation remains available"
                    )
        except PoolTimeout:
            raise ProtectedDatabaseCapacityError() from None
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

    _pool_type = _GovernancePool
    _profile = GOVERNANCE_PROFILE

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
        self._active: _GovernancePool | None = (
            self._pool_type(
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
    def _protected_command(owner: str, command_type: type[Command | Query]) -> bool:
        return (
            owner == GOVERNANCE_PROFILE
            and command_type.__module__ in _GOVERNANCE_COMMAND_MODULES
            and command_type.__name__ in _GOVERNANCE_COMMANDS
        )

    @classmethod
    def requires_protected(
        cls, registered: _ProtectedCommandRegistration, command_type: type[Command | Query]
    ) -> bool:
        return cls._protected_command(registered.owner, command_type)

    def record_registration(
        self,
        registered: _ProtectedCommandRegistration,
        command_type: type[Command | Query],
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
        command_type: type[Command | Query],
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
            # Admission must inspect the effective database authority even if
            # readiness checks are disabled or have not yet been requested.
            try:
                await pool.validate()
            except ProtectedDatabaseCapacityError:
                raise
            except Exception:
                self._active = None
                if self._leases.get(pool, 0) == 0:
                    await pool.close()
                raise
            if not self._gate.is_active(registration.generation):
                raise NotFoundError("Module contribution is not active")
            _logger.info(
                "Protected database execution selected",
                extra={
                    "protected_database_profile": self._profile,
                    "handler_generation_owner": registration.generation.owner,
                    "handler_generation_number": registration.generation.number,
                },
            )
            self._leases[pool] = self._leases.get(pool, 0) + 1
        try:
            yield pool.for_tenant(tenant)
        except PoolTimeout:
            raise ProtectedDatabaseCapacityError() from None
        finally:
            async with self._lock:
                self._leases[pool] -= 1
                last = self._leases[pool] == 0
                if last:
                    del self._leases[pool]
                retired = pool is not self._active
            if last and retired:
                await pool.close()

    @asynccontextmanager
    async def for_message(
        self,
        registered: _ProtectedCommandRegistration,
        message: Command | Query,
        tenant: TenantContext | None,
    ) -> AsyncGenerator[UnitOfWork]:
        async with self.for_command(registered, type(message), tenant) as unit:
            yield unit

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
            replacement = self._pool_type(
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
