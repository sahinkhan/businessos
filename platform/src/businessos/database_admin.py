"""Explicit administrative transition for pre-role-separation databases."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

MIGRATOR_ROLE = "businessos_migrator"
APPLICATION_ROLE = "businessos_app"
OPERATIONS_ROLE = "businessos_ops"
TRANSITION_LOCK = "businessos.database-role-transition.v1"


class DatabaseTransitionError(RuntimeError):
    """A credential-safe administrative transition failure."""


@dataclass(frozen=True, slots=True, repr=False)
class DatabaseRolePasswords:
    migrator: str
    application: str
    operations: str


def _role_exists(connection: psycopg.Connection[tuple[object, ...]], role: str) -> bool:
    row = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    return row is not None


def _ensure_role(
    connection: psycopg.Connection[tuple[object, ...]],
    role: str,
    password: str,
    *,
    bypass_rls: bool,
) -> None:
    identifier = sql.Identifier(role)
    if not _role_exists(connection, role):
        connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(identifier))
    bypass = sql.SQL("BYPASSRLS") if bypass_rls else sql.SQL("NOBYPASSRLS")
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT {} PASSWORD {}"
        ).format(identifier, bypass, sql.Literal(password))
    )


def _relation_exists(
    connection: psycopg.Connection[tuple[object, ...]],
    qualified_name: str,
) -> bool:
    return connection.execute("SELECT to_regclass(%s)", (qualified_name,)).fetchone() != (None,)


def _transfer_schema_objects(
    connection: psycopg.Connection[tuple[object, ...]],
    schema_name: str,
) -> None:
    schema = sql.Identifier(schema_name)
    connection.execute(
        sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(schema, sql.Identifier(MIGRATOR_ROLE))
    )
    rows = connection.execute(
        "SELECT c.relname, c.relkind FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'S', 'v', 'm') "
        "ORDER BY c.relname",
        (schema_name,),
    ).fetchall()
    relation_commands = {
        "r": sql.SQL("TABLE"),
        "p": sql.SQL("TABLE"),
        "S": sql.SQL("SEQUENCE"),
        "v": sql.SQL("VIEW"),
        "m": sql.SQL("MATERIALIZED VIEW"),
    }
    for relation_name, relation_kind in rows:
        command = relation_commands[str(relation_kind)]
        connection.execute(
            sql.SQL("ALTER {} {}.{} OWNER TO {}").format(
                command,
                schema,
                sql.Identifier(str(relation_name)),
                sql.Identifier(MIGRATOR_ROLE),
            )
        )


def _set_tenant_policy(
    connection: psycopg.Connection[tuple[object, ...]],
    schema_name: str,
    table_name: str,
) -> None:
    qualified_text = f"{schema_name}.{table_name}"
    if not _relation_exists(connection, qualified_text):
        return
    qualified = sql.Identifier(schema_name, table_name)
    policy = sql.Identifier(f"{table_name}_tenant_isolation")
    migration_policy = sql.Identifier(f"{table_name}_migration_access")
    connection.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(qualified))
    connection.execute(sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(qualified))
    connection.execute(sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(policy, qualified))
    connection.execute(
        sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(migration_policy, qualified)
    )
    tenant_expression = sql.SQL(
        "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    )
    connection.execute(
        sql.SQL("CREATE POLICY {} ON {} TO {} USING ({}) WITH CHECK ({})").format(
            policy,
            qualified,
            sql.Identifier(APPLICATION_ROLE),
            tenant_expression,
            tenant_expression,
        )
    )
    connection.execute(
        sql.SQL("CREATE POLICY {} ON {} TO {} USING (true) WITH CHECK (true)").format(
            migration_policy,
            qualified,
            sql.Identifier(MIGRATOR_ROLE),
        )
    )


def _correct_legacy_inbox_key(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    if not _relation_exists(connection, "eventing.inbox_receipts"):
        return
    columns = connection.execute(
        "SELECT array_agg(a.attname ORDER BY key_columns.ordinality) "
        "FROM pg_constraint AS c "
        "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS key_columns(attnum, ordinality) "
        "ON true JOIN pg_attribute AS a ON a.attrelid = c.conrelid "
        "AND a.attnum = key_columns.attnum "
        "WHERE c.conrelid = 'eventing.inbox_receipts'::regclass AND c.contype = 'p'"
    ).fetchone()
    if columns == (["tenant_id", "consumer", "event_id"],):
        return
    connection.execute(
        "ALTER TABLE eventing.inbox_receipts DROP CONSTRAINT IF EXISTS pk_inbox_receipts"
    )
    connection.execute(
        "ALTER TABLE eventing.inbox_receipts ADD CONSTRAINT pk_inbox_receipts "
        "PRIMARY KEY (tenant_id, consumer, event_id)"
    )


def _revoke_relation_access(
    connection: psycopg.Connection[tuple[object, ...]],
    schema_name: str,
    table_name: str,
) -> None:
    if not _relation_exists(connection, f"{schema_name}.{table_name}"):
        return
    connection.execute(
        sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC, {}, {}").format(
            sql.Identifier(schema_name, table_name),
            sql.Identifier(APPLICATION_ROLE),
            sql.Identifier(OPERATIONS_ROLE),
        )
    )


def _grant_exact_runtime_access(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    schema_grants = {
        "eventing": (APPLICATION_ROLE, OPERATIONS_ROLE),
        "platform_module": (APPLICATION_ROLE,),
        "mod_example_phase1_proof": (APPLICATION_ROLE,),
    }
    for schema_name, roles in schema_grants.items():
        if (
            connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema_name,)
            ).fetchone()
            is None
        ):
            continue
        connection.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, {}, {}").format(
                sql.Identifier(schema_name),
                sql.Identifier(APPLICATION_ROLE),
                sql.Identifier(OPERATIONS_ROLE),
            )
        )
        for role in roles:
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema_name), sql.Identifier(role)
                )
            )

    relation_grants = (
        ("eventing", "outbox_messages", APPLICATION_ROLE, sql.SQL("SELECT, INSERT")),
        ("eventing", "inbox_receipts", APPLICATION_ROLE, sql.SQL("SELECT, INSERT")),
        ("eventing", "outbox_messages", OPERATIONS_ROLE, sql.SQL("SELECT, UPDATE")),
        ("eventing", "inbox_receipts", OPERATIONS_ROLE, sql.SQL("SELECT, INSERT")),
        (
            "eventing",
            "event_subscriber_obligations",
            OPERATIONS_ROLE,
            sql.SQL("SELECT, INSERT"),
        ),
        ("platform_module", "module_runtime_state", APPLICATION_ROLE, sql.SQL("SELECT")),
        (
            "platform_module",
            "installed_module_migrations",
            APPLICATION_ROLE,
            sql.SQL("SELECT"),
        ),
        (
            "mod_example_phase1_proof",
            "proof_records",
            APPLICATION_ROLE,
            sql.SQL("SELECT, INSERT, UPDATE, DELETE"),
        ),
    )
    for schema_name, table_name, role, privileges in relation_grants:
        if not _relation_exists(connection, f"{schema_name}.{table_name}"):
            continue
        connection.execute(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                privileges,
                sql.Identifier(schema_name, table_name),
                sql.Identifier(role),
            )
        )


def transition_database_roles(admin_url: str, passwords: DatabaseRolePasswords) -> None:
    """Idempotently transfer a legacy Phase 1 database to separated roles."""
    try:
        with psycopg.connect(admin_url, row_factory=tuple_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (TRANSITION_LOCK,),
            )
            current_database = connection.execute("SELECT current_database()").fetchone()
            if current_database is None:
                raise DatabaseTransitionError("cannot identify the target database")
            database_name = str(current_database[0])

            _ensure_role(connection, MIGRATOR_ROLE, passwords.migrator, bypass_rls=False)
            _ensure_role(connection, APPLICATION_ROLE, passwords.application, bypass_rls=False)
            _ensure_role(connection, OPERATIONS_ROLE, passwords.operations, bypass_rls=True)
            connection.execute(
                sql.SQL("REVOKE {}, {} FROM {}").format(
                    sql.Identifier(MIGRATOR_ROLE),
                    sql.Identifier(OPERATIONS_ROLE),
                    sql.Identifier(APPLICATION_ROLE),
                )
            )
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database_name)
                )
            )
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}, {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(MIGRATOR_ROLE),
                    sql.Identifier(APPLICATION_ROLE),
                    sql.Identifier(OPERATIONS_ROLE),
                )
            )
            connection.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(MIGRATOR_ROLE)
                )
            )

            for schema_name in ("eventing", "platform_module", "mod_example_phase1_proof"):
                if (
                    connection.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema_name,)
                    ).fetchone()
                    is not None
                ):
                    _transfer_schema_objects(connection, schema_name)
            if _relation_exists(connection, "public.alembic_version"):
                connection.execute(
                    sql.SQL("ALTER TABLE public.alembic_version OWNER TO {}").format(
                        sql.Identifier(MIGRATOR_ROLE)
                    )
                )

            _correct_legacy_inbox_key(connection)
            for schema_name, table_name in (
                ("eventing", "outbox_messages"),
                ("eventing", "inbox_receipts"),
                ("mod_example_phase1_proof", "proof_records"),
            ):
                _set_tenant_policy(connection, schema_name, table_name)
            for schema_name, table_name in (
                ("eventing", "outbox_messages"),
                ("eventing", "inbox_receipts"),
                ("eventing", "event_subscriber_obligations"),
                ("platform_module", "module_runtime_state"),
                ("platform_module", "installed_module_migrations"),
                ("mod_example_phase1_proof", "proof_records"),
            ):
                _revoke_relation_access(connection, schema_name, table_name)
            _grant_exact_runtime_access(connection)
    except DatabaseTransitionError:
        raise
    except Exception:
        raise DatabaseTransitionError("database role transition failed") from None
