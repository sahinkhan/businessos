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
