import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql


@pytest.fixture
def postgres_database_url() -> Iterator[str]:
    admin_url = os.getenv("BOS_TEST_DATABASE_ADMIN_URL")
    if admin_url is None:
        pytest.skip("BOS_TEST_DATABASE_ADMIN_URL is not configured")

    database_name = f"businessos_test_{uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    test_url = admin_url.rsplit("/", 1)[0] + f"/{database_name}"
    sqlalchemy_url = test_url.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        yield sqlalchemy_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


@pytest.fixture
def migrated_database_url(postgres_database_url: str) -> Iterator[str]:
    config = Config("alembic.ini")
    config.attributes["database_url"] = postgres_database_url
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    try:
        yield postgres_database_url
    finally:
        command.downgrade(config, "base")
