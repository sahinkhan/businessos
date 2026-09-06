import psycopg
import pytest
from alembic import command
from alembic.config import Config


@pytest.mark.integration
@pytest.mark.postgres
def test_alembic_upgrades_empty_database_and_is_replayable(
    postgres_database_url: str,
    postgres_migration_database_url: str,
) -> None:
    config = Config("alembic.ini")
    config.attributes["database_url"] = postgres_migration_database_url
    config.set_main_option("sqlalchemy.url", postgres_migration_database_url)

    command.upgrade(config, "head")

    connection_url = postgres_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url) as connection:
        rows = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('eventing', 'platform_module') "
            "ORDER BY table_schema, table_name"
        ).fetchall()

    assert rows == [
        ("eventing", "inbox_receipts"),
        ("eventing", "outbox_messages"),
        ("platform_module", "module_runtime_state"),
    ]

    command.downgrade(config, "base")
    command.upgrade(config, "head")
