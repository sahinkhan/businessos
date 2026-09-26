"""Fail-closed ADR-022 role prerequisite for forward migration grants."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def assert_governance_role_safe(connection: Connection) -> None:
    """Verify the protected role before any migration grants authority to it."""
    role = connection.execute(
        text(
            "SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
            "rolinherit, rolbypassrls FROM pg_roles "
            "WHERE rolname = 'businessos_governance'"
        )
    ).one_or_none()
    if role is None or tuple(role[1:]) != (True, False, False, False, False, False):
        raise RuntimeError("unsafe Governance migration role prerequisites")
    role_oid = role[0]
    unsafe = connection.execute(
        text(
            "SELECT "
            "EXISTS (SELECT 1 FROM pg_auth_members "
            "WHERE member = :role_oid OR roleid = :role_oid), "
            "EXISTS (SELECT 1 FROM pg_database WHERE datdba = :role_oid "
            "UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner = :role_oid "
            "UNION ALL SELECT 1 FROM pg_class WHERE relowner = :role_oid "
            "UNION ALL SELECT 1 FROM pg_proc WHERE proowner = :role_oid), "
            "has_database_privilege('businessos_governance', current_database(), 'CONNECT')"
        ),
        {"role_oid": role_oid},
    ).one()
    if unsafe != (False, False, True):
        raise RuntimeError("unsafe Governance migration role prerequisites")


def assert_ordinary_governance_write_denied(connection: Connection) -> None:
    """Abort an upgrade if a legacy grant still admits ordinary authority writes."""
    memberships = connection.execute(
        text(
            "SELECT 1 FROM pg_auth_members AS link "
            "JOIN pg_roles AS member ON member.oid = link.member "
            "JOIN pg_roles AS granted ON granted.oid = link.roleid "
            "WHERE member.rolname IN ('businessos_app', 'businessos_worker') "
            "AND NOT (member.rolname = 'businessos_worker' "
            "AND granted.rolname = 'businessos_app') LIMIT 1"
        )
    ).first()
    if memberships is not None:
        raise RuntimeError("ordinary Governance role membership retains a write path")

    for table in ("retention_policies", "legal_holds"):
        for role in ("businessos_app", "businessos_worker"):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                permitted = connection.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": f"platform_gov.{table}", "privilege": privilege},
                ).scalar_one()
                if permitted:
                    raise RuntimeError("ordinary Governance table mutation remains available")
            for privilege in ("INSERT", "UPDATE"):
                permitted = connection.execute(
                    text("SELECT has_any_column_privilege(:role, :table, :privilege)"),
                    {"role": role, "table": f"platform_gov.{table}", "privilege": privilege},
                ).scalar_one()
                if permitted:
                    raise RuntimeError("ordinary Governance column mutation remains available")

    indirect = connection.execute(
        text(
            "SELECT 1 FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('v', 'm') "
            "AND EXISTS (SELECT 1 FROM pg_rewrite AS rw "
            "JOIN pg_depend AS dep ON dep.objid = rw.oid "
            "WHERE rw.ev_class = c.oid AND dep.refobjid IN "
            "('platform_gov.retention_policies'::regclass, "
            "'platform_gov.legal_holds'::regclass)) "
            "AND (has_table_privilege('businessos_app', c.oid, 'INSERT, UPDATE, DELETE') "
            "OR has_table_privilege('businessos_worker', c.oid, 'INSERT, UPDATE, DELETE')) "
            "UNION ALL SELECT 1 FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND n.nspname NOT LIKE 'pg_%' AND p.prosecdef "
            "AND NOT (n.nspname = 'platform_identity' "
            "AND p.proname = 'admit_workload') "
            "AND (has_function_privilege('businessos_app', p.oid, 'EXECUTE') "
            "OR has_function_privilege('businessos_worker', p.oid, 'EXECUTE')) "
            "UNION ALL SELECT 1 FROM pg_default_acl AS d "
            "LEFT JOIN pg_namespace AS n ON n.oid = d.defaclnamespace "
            "CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a "
            "WHERE (n.nspname = 'platform_gov' OR d.defaclnamespace = 0) "
            "AND d.defaclobjtype = 'r' "
            "AND a.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE') "
            "AND (a.grantee = 0 OR a.grantee IN "
            "(SELECT oid FROM pg_roles WHERE rolname IN "
            "('businessos_app', 'businessos_worker'))) LIMIT 1"
        )
    ).first()
    if indirect is not None:
        raise RuntimeError("indirect ordinary Governance mutation remains available")
