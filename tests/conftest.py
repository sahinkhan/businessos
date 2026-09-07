import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from businessos.context import TenantContext
from businessos.persistence import Database

TenantSessions = Callable[[Database], Callable[[TenantContext], async_sessionmaker[AsyncSession]]]


@dataclass(frozen=True, slots=True)
class PostgreSQLTestDatabase:
    administrator_url: str
    migration_url: str
    runtime_url: str
    operations_url: str


def _database_url(base_url: str, database_name: str, *, sqlalchemy: bool = False) -> str:
    url = base_url.rsplit("/", 1)[0] + f"/{database_name}"
    if sqlalchemy:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture
def postgres_database() -> Iterator[PostgreSQLTestDatabase]:
    admin_url = os.getenv("BOS_TEST_DATABASE_ADMIN_URL")
    if admin_url is None:
        pytest.skip("BOS_TEST_DATABASE_ADMIN_URL is not configured")
    runtime_url = os.getenv("BOS_TEST_DATABASE_RUNTIME_URL")
    if runtime_url is None:
        pytest.skip("BOS_TEST_DATABASE_RUNTIME_URL is not configured")
    operations_url = os.getenv("BOS_TEST_DATABASE_OPERATIONS_URL")
    if operations_url is None:
        pytest.skip("BOS_TEST_DATABASE_OPERATIONS_URL is not configured")
    migration_url = os.getenv("BOS_TEST_DATABASE_MIGRATION_URL")
    if migration_url is None:
        pytest.skip("BOS_TEST_DATABASE_MIGRATION_URL is not configured")

    database_name = f"businessos_test_{uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER businessos_migrator").format(
                sql.Identifier(database_name)
            )
        )

    migration_database_url = _database_url(admin_url, database_name)
    with psycopg.connect(migration_database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database_name))
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO businessos_app, businessos_ops").format(
                sql.Identifier(database_name)
            )
        )

    try:
        yield PostgreSQLTestDatabase(
            administrator_url=_database_url(admin_url, database_name),
            migration_url=_database_url(migration_url, database_name, sqlalchemy=True),
            runtime_url=_database_url(runtime_url, database_name, sqlalchemy=True),
            operations_url=_database_url(operations_url, database_name, sqlalchemy=True),
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


@pytest.fixture
def postgres_database_url(postgres_database: PostgreSQLTestDatabase) -> str:
    return postgres_database.runtime_url


@pytest.fixture
def postgres_migration_database_url(postgres_database: PostgreSQLTestDatabase) -> str:
    return postgres_database.migration_url


@pytest.fixture
def postgres_operations_database_url(postgres_database: PostgreSQLTestDatabase) -> str:
    return postgres_database.operations_url


@pytest.fixture
def migrated_database_url(postgres_database: PostgreSQLTestDatabase) -> Iterator[str]:
    config = Config("alembic.ini")
    config.attributes["database_url"] = postgres_database.migration_url
    config.set_main_option("sqlalchemy.url", postgres_database.migration_url)
    command.upgrade(config, "head")
    try:
        yield postgres_database.runtime_url
    finally:
        command.downgrade(config, "base")


@pytest.fixture
def tenant_sessions(postgres_database: PostgreSQLTestDatabase) -> TenantSessions:
    """Explicit test provisioning authority, separate from runtime factory behavior."""
    from sqlalchemy.engine import make_url

    from businessos.context import TenantContext
    from businessos.database_admin import provision_tenant_login
    from businessos.persistence import Database

    def bind(database: Database) -> Callable[[TenantContext], async_sessionmaker[AsyncSession]]:
        def sessions(context: TenantContext) -> async_sessionmaker[AsyncSession]:
            settings = database._settings
            if context.tenant_id not in settings.tenant_database_urls:
                with psycopg.connect(postgres_database.administrator_url) as connection:
                    role = provision_tenant_login(
                        connection, tenant_id=context.tenant_id, password="test-only"
                    )
                settings.tenant_database_urls[context.tenant_id] = (
                    make_url(settings.database_url)
                    .set(username=role, password="test-only")
                    .render_as_string(hide_password=False)
                )
            return database.sessions_for_tenant(context)

        return sessions

    return bind


@pytest.fixture
def tenant_urls(
    postgres_database: PostgreSQLTestDatabase,
) -> Callable[[TenantContext], dict[UUID, str]]:
    from sqlalchemy.engine import make_url

    from businessos.database_admin import provision_tenant_login

    def provision(context: TenantContext) -> dict[UUID, str]:
        with psycopg.connect(postgres_database.administrator_url) as connection:
            role = provision_tenant_login(
                connection, tenant_id=context.tenant_id, password="test-only"
            )
        return {
            context.tenant_id: make_url(postgres_database.runtime_url)
            .set(username=role, password="test-only")
            .render_as_string(hide_password=False)
        }

    return provision
