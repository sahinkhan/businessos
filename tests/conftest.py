import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql


@dataclass(frozen=True, slots=True)
class PostgreSQLTestDatabase:
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
            migration_url=_database_url(admin_url, database_name, sqlalchemy=True),
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
