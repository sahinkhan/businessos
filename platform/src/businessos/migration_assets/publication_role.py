"""ADR-024 deployment prerequisites; migrations never create runtime credentials."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

PUBLICATION_ROLE = "businessos_ui_publication"
COUNTER_OWNER = "businessos_metadata_fence_owner"


def assert_publication_roles_safe(connection: Connection) -> None:
    for name, login in ((PUBLICATION_ROLE, True), (COUNTER_OWNER, False)):
        role = connection.execute(
            text(
                "SELECT oid,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolinherit,"
                "rolbypassrls,rolreplication FROM pg_roles WHERE rolname=:name"
            ),
            {"name": name},
        ).one_or_none()
        if role is None or tuple(role[1:]) != (login, False, False, False, False, False, False):
            raise RuntimeError("unsafe ADR-024 migration role prerequisites")
        # No edge into/out of the runtime role means no transitive SET ROLE path.
        # The migrator alone may own/maintain the NOLOGIN trigger functions.
        unsafe = connection.execute(
            text(
                "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
                "WHERE (m.member=:oid OR m.roleid=:oid) AND NOT "
                "(:counter AND m.roleid=:oid AND r.rolname='businessos_migrator') "
                "UNION ALL SELECT 1 FROM pg_database WHERE datdba=:oid "
                "UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=:oid "
                "UNION ALL SELECT 1 FROM pg_class WHERE relowner=:oid LIMIT 1"
            ),
            {"oid": role[0], "counter": name == COUNTER_OWNER},
        ).first()
        if unsafe is not None:
            raise RuntimeError("unsafe ADR-024 ownership or membership")
    if not connection.execute(
        text("SELECT pg_has_role(current_user,'businessos_metadata_fence_owner','SET')")
    ).scalar_one():
        raise RuntimeError("ADR-024 NOLOGIN function ownership requires migrator membership")
