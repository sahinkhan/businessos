from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.eventing import Inbox
from businessos.persistence import (
    Database,
    InboxReceipt,
    OutboxMessage,
    PendingOutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)
from tests.conftest import TenantSessions


def _settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, database_pool_size=2)


def _tenant() -> TenantContext:
    return TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")


def _message(tenant: TenantContext, value: str) -> PendingOutboxMessage:
    return PendingOutboxMessage(
        tenant_id=tenant.tenant_id,
        event_type="proof.tenant_isolation",
        schema_version=1,
        correlation_id=f"correlation-{value}",
        payload={"value": value},
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_runtime_role_is_non_owner_non_bypass_and_rls_is_forced(
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    async with database.sessions() as session:
        role = (
            await session.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        database_owner = await session.scalar(
            text(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
            )
        )
        tables = (
            await session.execute(
                text(
                    "SELECT n.nspname, c.relname, pg_get_userbyid(c.relowner), "
                    "c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'eventing' "
                    "AND c.relname IN "
                    "('event_subscriber_obligations', 'inbox_receipts', 'outbox_messages') "
                    "ORDER BY c.relname"
                )
            )
        ).all()

    await database.close()

    assert tuple(role) == ("businessos_app", False, False)
    assert database_owner == "businessos_migrator"
    assert [(row[0], row[1]) for row in tables] == [
        ("eventing", "event_subscriber_obligations"),
        ("eventing", "inbox_receipts"),
        ("eventing", "outbox_messages"),
    ]
    assert all(row[2] == "businessos_migrator" for row in tables)
    assert tuple(tables[0][3:]) == (False, False)
    assert all(row[3] is True and row[4] is True for row in tables[1:])


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_eventing_tables_are_isolated_and_missing_context_fails_closed(
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
    tenant_a = _tenant()
    tenant_b = _tenant()
    message_a = _message(tenant_a, "a")
    message_b = _message(tenant_b, "b")
    shared_event_id = uuid4()
    inbox = Inbox()

    for tenant, message in ((tenant_a, message_a), (tenant_b, message_b)):
        async with factory.for_tenant(tenant) as unit_of_work:
            assert unit_of_work.session is not None
            unit_of_work.add_outbox(message)
            assert await inbox.claim(
                unit_of_work.session,
                consumer="proof.consumer",
                event_id=shared_event_id,
                tenant_id=tenant.tenant_id,
            )
            await unit_of_work.commit()

    async with factory.for_tenant(tenant_a) as unit_of_work:
        assert unit_of_work.session is not None
        visible_outbox = (await unit_of_work.session.scalars(select(OutboxMessage))).all()
        visible_inbox = (await unit_of_work.session.scalars(select(InboxReceipt))).all()
        hidden = await unit_of_work.session.get(OutboxMessage, message_b.event_id)
        visible_outbox_ids = [row.id for row in visible_outbox]
        visible_inbox_tenants = [row.tenant_id for row in visible_inbox]

    assert visible_outbox_ids == [message_a.event_id]
    assert visible_inbox_tenants == [tenant_a.tenant_id]
    assert hidden is None

    async with database.sessions() as session:
        assert (await session.scalars(select(OutboxMessage))).all() == []
        session.add(
            OutboxMessage(
                id=uuid4(),
                tenant_id=tenant_a.tenant_id,
                event_type="proof.missing_context",
                schema_version=1,
                occurred_at=message_a.occurred_at,
                correlation_id="missing-context",
                payload={},
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()

    async with factory.for_tenant(tenant_a) as unit_of_work:
        unit_of_work.add_outbox(_message(tenant_b, "forged"))
        with pytest.raises(DBAPIError):
            await unit_of_work.commit()

    await database.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_runtime_cannot_disable_rls_and_operations_access_is_explicit(
    migrated_database_url: str,
    postgres_operations_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    runtime = Database(_settings(migrated_database_url))
    operations = Database(_settings(postgres_operations_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        runtime.sessions, tenant_sessions=tenant_sessions(runtime)
    )
    tenant_a = _tenant()
    tenant_b = _tenant()

    for tenant, value in ((tenant_a, "a"), (tenant_b, "b")):
        async with factory.for_tenant(tenant) as unit_of_work:
            unit_of_work.add_outbox(_message(tenant, value))
            await unit_of_work.commit()

    async with runtime.sessions() as session:
        can_access_obligations = await session.scalar(
            text(
                "SELECT has_table_privilege(current_user, "
                "'eventing.event_subscriber_obligations', 'SELECT')"
            )
        )
        with pytest.raises(DBAPIError):
            await session.execute(
                text("ALTER TABLE eventing.outbox_messages DISABLE ROW LEVEL SECURITY")
            )
        await session.rollback()
        await session.execute(text("SET LOCAL row_security = off"))
        with pytest.raises(DBAPIError):
            await session.scalars(select(OutboxMessage))
        await session.rollback()

    async with operations.sessions() as session:
        role = await session.scalar(text("SELECT current_user"))
        rows = (await session.scalars(select(OutboxMessage))).all()
        can_create = await session.scalar(
            text("SELECT has_schema_privilege(current_user, 'eventing', 'CREATE')")
        )
        can_update_outbox = await session.scalar(
            text("SELECT has_table_privilege(current_user, 'eventing.outbox_messages', 'UPDATE')")
        )
        can_access_modules = await session.scalar(
            text(
                "SELECT has_table_privilege(current_user, c.oid, 'SELECT') "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'platform_module' "
                "AND c.relname = 'module_runtime_state'"
            )
        )
        can_read_obligations = await session.scalar(
            text(
                "SELECT has_table_privilege(current_user, "
                "'eventing.event_subscriber_obligations', 'SELECT')"
            )
        )
        can_insert_obligations = await session.scalar(
            text(
                "SELECT has_table_privilege(current_user, "
                "'eventing.event_subscriber_obligations', 'INSERT')"
            )
        )
        can_mutate_obligations = await session.scalar(
            text(
                "SELECT has_table_privilege(current_user, "
                "'eventing.event_subscriber_obligations', 'UPDATE, DELETE')"
            )
        )

    await runtime.close()
    await operations.close()

    assert role == "businessos_ops"
    assert len(rows) == 2
    assert can_create is False
    assert can_update_outbox is True
    assert can_access_modules is False
    assert can_access_obligations is False
    assert can_read_obligations is True
    assert can_insert_obligations is True
    assert can_mutate_obligations is False
