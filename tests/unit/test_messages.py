from types import TracebackType
from typing import ClassVar, Self
from uuid import UUID, uuid4

import pytest

from businessos.context import RequestContext, TenantContext
from businessos.di import Container
from businessos.errors import BusinessOSError
from businessos.messages import (
    Command,
    DomainEvent,
    EventBus,
    HandlingContext,
    MessageDispatcher,
    Query,
)
from businessos.persistence import PendingOutboxMessage, TransactionalPersistence, UnitOfWork
from businessos.security import Authorizer


class ChangeName(Command):
    name: str


class ReadName(Query):
    pass


class NameChanged(DomainEvent):
    event_type: ClassVar[str] = "example.name_changed"
    name: str


class FakeUnitOfWork:
    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline
        self.messages: list[PendingOutboxMessage] = []
        self.committed = False

    @property
    def persistence(self) -> TransactionalPersistence:
        raise NotImplementedError

    async def __aenter__(self) -> Self:
        self.timeline.append("begin")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.timeline.append("rollback" if exc_type or not self.committed else "close")

    async def commit(self) -> None:
        self.committed = True
        self.timeline.append("commit")

    async def rollback(self) -> None:
        self.timeline.append("rollback")

    def add_outbox(self, message: PendingOutboxMessage) -> None:
        self.messages.append(message)
        self.timeline.append("outbox")


class FakeUnitOfWorkFactory:
    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline
        self.created: list[FakeUnitOfWork] = []

    def for_tenant(self, context: TenantContext) -> UnitOfWork:
        return self._create()

    def system(self) -> UnitOfWork:
        return self._create()

    def _create(self) -> FakeUnitOfWork:
        unit_of_work = FakeUnitOfWork(self.timeline)
        self.created.append(unit_of_work)
        return unit_of_work


class DenyPolicy:
    async def is_allowed(
        self,
        principal_id: UUID,
        tenant: TenantContext,
        permission: str,
    ) -> bool:
        return False


@pytest.mark.asyncio
async def test_command_commits_outbox_before_in_process_event_delivery() -> None:
    timeline: list[str] = []
    factory = FakeUnitOfWorkFactory(timeline)
    events = EventBus()
    dispatcher = MessageDispatcher(factory, events)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    context = RequestContext(correlation_id="c1", trace_id="t1", tenant=tenant)

    async def handle(command: ChangeName, handling: HandlingContext) -> object:
        timeline.append("handler")
        handling.emit(
            NameChanged(
                tenant_id=tenant.tenant_id,
                correlation_id=context.correlation_id,
                name=command.name,
            )
        )
        return command.name

    async def consume(
        event: NameChanged,
        request: RequestContext,
        dependencies: object,
    ) -> None:
        assert request == context
        timeline.append(f"event:{event.name}")

    dispatcher.commands.register(ChangeName, "example", handle)
    events.subscribe(NameChanged, "example.consumer", consume)

    container = Container()
    async with container.request_scope() as dependencies:
        result = await dispatcher.command(ChangeName(name="new"), context, dependencies)

    assert result == "new"
    assert timeline == ["begin", "handler", "outbox", "commit", "close", "event:new"]
    assert factory.created[0].messages[0].event_type == "example.name_changed"


@pytest.mark.asyncio
async def test_query_uses_read_transaction_without_commit() -> None:
    timeline: list[str] = []
    factory = FakeUnitOfWorkFactory(timeline)
    dispatcher = MessageDispatcher(factory, EventBus())
    context = RequestContext()

    async def handle(_: ReadName, __: HandlingContext) -> object:
        timeline.append("query")
        return "value"

    dispatcher.queries.register(ReadName, "example", handle)
    container = Container()
    async with container.request_scope() as dependencies:
        result = await dispatcher.query(ReadName(), context, dependencies)

    assert result == "value"
    assert timeline == ["begin", "query", "rollback"]


@pytest.mark.parametrize(
    ("kind", "expected_code"), [("tenant", "forbidden"), ("system", "unauthenticated")]
)
@pytest.mark.asyncio
async def test_command_authorization_precedes_transaction_and_handler(
    kind: str,
    expected_code: str,
) -> None:
    timeline: list[str] = []
    factory = FakeUnitOfWorkFactory(timeline)
    authorizer = Authorizer(DenyPolicy())
    events = EventBus(authorizer=authorizer)
    dispatcher = MessageDispatcher(factory, events, authorizer=authorizer)

    async def handle(_: ChangeName, __: HandlingContext) -> object:
        timeline.append("handler")
        return None

    dispatcher.commands.register(
        ChangeName,
        "example",
        handle,
        permission="example.change-name",
    )
    context = RequestContext(
        tenant=TenantContext(uuid4(), uuid4(), uuid4()) if kind == "tenant" else None
    )
    container = Container()
    async with container.request_scope() as dependencies:
        with pytest.raises(BusinessOSError) as raised:
            await dispatcher.command(ChangeName(name="blocked"), context, dependencies)

    assert raised.value.code == expected_code
    assert factory.created == []
    assert timeline == []


@pytest.mark.asyncio
async def test_query_and_event_permissions_are_enforced() -> None:
    timeline: list[str] = []
    factory = FakeUnitOfWorkFactory(timeline)
    authorizer = Authorizer(DenyPolicy())
    events = EventBus(authorizer=authorizer)
    dispatcher = MessageDispatcher(factory, events, authorizer=authorizer)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    context = RequestContext(tenant=tenant)

    async def query_handler(_: ReadName, __: HandlingContext) -> object:
        timeline.append("query")
        return None

    async def event_handler(
        _: NameChanged,
        __: RequestContext,
        ___: object,
    ) -> None:
        timeline.append("event")

    dispatcher.queries.register(
        ReadName,
        "example",
        query_handler,
        permission="example.read-name",
    )
    events.subscribe(
        NameChanged,
        "example.consumer",
        event_handler,
        permission="example.consume-name",
    )
    container = Container()
    async with container.request_scope() as dependencies:
        with pytest.raises(BusinessOSError) as query_error:
            await dispatcher.query(ReadName(), context, dependencies)
        with pytest.raises(BusinessOSError) as event_error:
            await events.publish(
                NameChanged(
                    tenant_id=tenant.tenant_id,
                    correlation_id=context.correlation_id,
                    name="blocked",
                ),
                context,
                dependencies,
            )

    assert query_error.value.code == "forbidden"
    assert event_error.value.code == "forbidden"
    assert factory.created == []
    assert timeline == []
