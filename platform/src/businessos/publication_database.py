"""Kernel-private ADR-024 database profile; never a dispatcher handler UOW."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import text

from businessos.errors import ConfigurationError
from businessos.metadata_execution import (
    MetadataDatabaseExecutionAuthority,
    _MetadataPool,  # pyright: ignore[reportPrivateUsage] -- kernel-private pool validation
)

if TYPE_CHECKING:
    from businessos.messages import Command, Query


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

    @staticmethod
    def _protected_command(owner: str, command_type: type[Command | Query]) -> bool:
        return (
            owner == "foundation.metadata"
            and command_type.__module__ == "businessos_metadata.module"
            and command_type.__name__
            in {"PublishUIOverlay", "ReactivateUIOverlay", "RetireUIOverlay"}
        )
