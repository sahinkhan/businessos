"""Real PostgreSQL adversarial gate for immutable tenant login identity."""

from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from businessos.config import Settings
from businessos.database_admin import provision_tenant_login
from businessos.persistence import Database, PendingOutboxMessage, SQLAlchemyUnitOfWorkFactory
from businessos.persistence.repository import TenantRepository
from businessos.sdk import TenantContext
from tests.conftest import PostgreSQLTestDatabase


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_public_persistence_cannot_replace_database_tenant(
    migrated_database_url: str,
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    tenant_a = TenantContext(uuid4(), uuid4(), uuid4())
    tenant_b = TenantContext(tenant_a.installation_id, uuid4(), uuid4())
    urls = {}
    for tenant in (tenant_a, tenant_b):
        with psycopg.connect(postgres_database.administrator_url) as connection:
            role = provision_tenant_login(
                connection, tenant_id=tenant.tenant_id, password="test-only"
            )
        urls[tenant.tenant_id] = (
            make_url(migrated_database_url)
            .set(username=role, password="test-only")
            .render_as_string(hide_password=False)
        )
    database = Database(
        Settings(environment="test", database_url=migrated_database_url, tenant_database_urls=urls)
    )
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=database.sessions_for_tenant
    )
    message = PendingOutboxMessage(
        tenant_id=tenant_b.tenant_id,
        event_type="proof.tenant_binding_attack",
        schema_version=1,
        correlation_id="batch-a-adversarial",
        payload={},
    )
    try:
        async with factory.for_tenant(tenant_b) as transaction:
            transaction.add_outbox(message)
            await transaction.commit()
        async with factory.for_tenant(tenant_a) as transaction:
            repository = TenantRepository(
                lambda: transaction.persistence, "example.proof", tenant_a.tenant_id, lambda: None
            )
            assert not hasattr(repository, "execute")
            assert not hasattr(repository, "commit")
            query = text("SELECT id FROM eventing.outbox_messages WHERE id = :id")
            assert (
                await transaction.persistence.execute(query, {"id": message.event_id})
            ).all() == []
            # Use the internal raw adapter for a stronger database-level attack;
            # the SDK no longer accepts SQL at all.
            await transaction.persistence.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_b.tenant_id)},
            )
            assert (
                await transaction.persistence.execute(query, {"id": message.event_id})
            ).all() == []
            assert (
                await transaction.persistence.execute(
                    text("SELECT platform_security.current_tenant_id()")
                )
            ).scalar_one() == tenant_a.tenant_id
        async with factory.for_tenant(tenant_b) as transaction:
            assert (
                await transaction.persistence.execute(query, {"id": message.event_id})
            ).scalar_one() == message.event_id
    finally:
        await database.close()
