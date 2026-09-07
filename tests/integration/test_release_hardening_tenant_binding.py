"""Batch A release gate: module SQL must not replace the trusted tenant binding."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from businessos.config import Settings
from businessos.persistence import Database, PendingOutboxMessage, SQLAlchemyUnitOfWorkFactory
from businessos.sdk import TenantContext, TransactionalPersistence


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_public_persistence_cannot_replace_database_tenant(
    migrated_database_url: str,
) -> None:
    database = Database(Settings(environment="test", database_url=migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    tenant_a = TenantContext(uuid4(), uuid4(), uuid4())
    tenant_b = TenantContext(tenant_a.installation_id, uuid4(), uuid4())
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
            persistence: TransactionalPersistence = transaction.persistence
            query = text("SELECT id FROM eventing.outbox_messages WHERE id = :id")
            assert (await persistence.execute(query, {"id": message.event_id})).all() == []
            try:
                await persistence.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_b.tenant_id)},
                )
                visible = (await persistence.execute(query, {"id": message.event_id})).all()
            except DBAPIError:
                # Denying the replacement or aborting this transaction is fail-closed.
                return
            assert visible == [], "Public module SQL replaced the trusted tenant and read tenant B"
    finally:
        await database.close()
