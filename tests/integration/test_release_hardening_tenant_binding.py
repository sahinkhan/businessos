"""Batch A release gate: module SQL must not replace the trusted tenant binding."""

from uuid import uuid4

import pytest
from sqlalchemy import text

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
    own_message = PendingOutboxMessage(
        tenant_id=tenant_a.tenant_id,
        event_type="proof.tenant_binding_control",
        schema_version=1,
        correlation_id="batch-a-adversarial",
        payload={},
    )
    try:
        async with factory.for_tenant(tenant_a) as transaction:
            transaction.add_outbox(own_message)
            await transaction.commit()

        async with factory.for_tenant(tenant_b) as transaction:
            transaction.add_outbox(message)
            await transaction.commit()

        async with factory.for_tenant(tenant_a) as transaction:
            persistence: TransactionalPersistence = transaction.persistence
            query = text("SELECT id FROM eventing.outbox_messages WHERE id IN (:own_id, :other_id)")
            parameters = {"own_id": own_message.event_id, "other_id": message.event_id}
            expected = [own_message.event_id]
            assert (await persistence.execute(query, parameters)).scalars().all() == expected
            session_identity = (await persistence.execute(text("SELECT session_user"))).scalar_one()

            # This mutation must succeed: an aborted transaction or database error
            # cannot substitute for proving that RLS ignores a caller-writable GUC.
            replacement = await persistence.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_b.tenant_id)},
            )
            assert replacement.scalar_one() == str(tenant_b.tenant_id)
            assert (
                await persistence.execute(text("SELECT current_setting('app.tenant_id')"))
            ).scalar_one() == str(tenant_b.tenant_id)
            assert (
                await persistence.execute(text("SELECT session_user"))
            ).scalar_one() == session_identity

            visible = (await persistence.execute(query, parameters)).scalars().all()
            assert visible == expected, (
                "Changing a custom GUC changed the RLS tenant identity: "
                "tenant A must remain visible and tenant B must remain hidden"
            )
    finally:
        await database.close()
