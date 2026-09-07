import asyncio
from collections.abc import Mapping
from types import TracebackType
from typing import ClassVar, Self, cast
from uuid import UUID, uuid4

import pytest

from businessos.activation import ContributionGate
from businessos.context import RequestContext, TenantContext
from businessos.di import Container
from businessos.errors import BusinessOSError, ConflictError, DeliveryUnavailableError
from businessos.messages import (
    Command,
    DomainEvent,
    EventBus,
    EventHandlingContext,
    HandlingContext,
    Message,
    MessageDispatcher,
    Query,
)
from businessos.persistence import PendingOutboxMessage, TransactionalPersistence, UnitOfWork
from businessos.security import Authorizer
from businessos.telemetry import configure_telemetry, server_span


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

    async def claim_inbox(self, *, consumer: str, event_id: UUID, tenant_id: UUID) -> bool:
        return True


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
async def test_command_commits_outbox_without_direct_event_delivery() -> None:
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
        handling: EventHandlingContext,
    ) -> None:
        assert handling.request == context
        timeline.append(f"event:{event.name}")

    dispatcher.commands.register(ChangeName, "example", handle)
    events.subscribe(NameChanged, "example.consumer", consume)

    container = Container()
    configure_telemetry(service_name="businessos-tests", service_version="0")
    with server_span(
        "POST",
        "/names",
        {"traceparent": ("00-0123456789abcdef0123456789abcdef-0123456789abcdef-01")},
    ):
        async with container.request_scope() as dependencies:
            result = await dispatcher.command(ChangeName(name="new"), context, dependencies)

    assert result == "new"
    assert timeline == ["begin", "handler", "outbox", "commit", "close"]
    assert factory.created[0].messages[0].event_type == "example.name_changed"
    trace_context = factory.created[0].messages[0].payload["trace_context"]
    assert isinstance(trace_context, dict)
    traceparent = cast(Mapping[str, object], trace_context).get("traceparent")
    assert isinstance(traceparent, str)
    assert traceparent.startswith("00-0123456789abcdef0123456789abcdef-")


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
        __: EventHandlingContext,
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
            event = NameChanged(
                tenant_id=tenant.tenant_id,
                correlation_id=context.correlation_id,
                name="blocked",
            )
            subscriber = events.subscribers(event)[0]
            await events.authorize(context, subscriber.permission)
            await events.invoke(
                subscriber,
                event,
                EventHandlingContext(context, dependencies, FakeUnitOfWork(timeline)),
            )

    assert query_error.value.code == "forbidden"
    assert event_error.value.code == "forbidden"
    assert factory.created == []
    assert timeline == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_kind", ["command", "query"])
async def test_authorization_and_invocation_hold_one_generation(
    dispatch_kind: str,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    authorized: list[str] = []
    invoked: list[str] = []
    tenant = TenantContext(uuid4(), uuid4(), uuid4())

    class BlockingPolicy:
        async def is_allowed(
            self,
            principal_id: UUID,
            context: TenantContext,
            permission: str,
        ) -> bool:
            authorized.append(permission)
            entered.set()
            await release.wait()
            return permission == "old.permission"

    gate = ContributionGate()
    generation = gate.reserve("example")
    factory = FakeUnitOfWorkFactory([])
    dispatcher = MessageDispatcher(
        factory,
        EventBus(),
        gate,
        Authorizer(BlockingPolicy()),
    )

    async def old_handler(_: Message, __: HandlingContext) -> object:
        invoked.append("old")
        return "old"

    registry = dispatcher.commands if dispatch_kind == "command" else dispatcher.queries
    message: Command | Query = ChangeName(name="old") if dispatch_kind == "command" else ReadName()
    registry.register(
        type(message),
        "example",
        old_handler,
        generation=generation,
        permission="old.permission",
    )
    gate.publish(generation)
    context = RequestContext(tenant=tenant)
    container = Container()
    async with container.request_scope() as dependencies:
        if dispatch_kind == "command":
            task = asyncio.create_task(
                dispatcher.command(cast(Command, message), context, dependencies)
            )
        else:
            task = asyncio.create_task(
                dispatcher.query(cast(Query, message), context, dependencies)
            )
        await entered.wait()
        drain = asyncio.create_task(gate.close_and_drain(generation, timeout_seconds=1))
        await asyncio.sleep(0)
        assert not drain.done()
        release.set()
        assert await task == "old"
        await drain

    assert authorized == ["old.permission"]
    assert invoked == ["old"]


@pytest.mark.asyncio
async def test_durable_subscriber_is_unavailable_while_generation_is_draining() -> None:
    gate = ContributionGate()
    generation = gate.reserve("example")
    events = EventBus(gate)

    async def consume(_: NameChanged, __: EventHandlingContext) -> None:
        return None

    events.subscribe(
        NameChanged,
        "example.consumer",
        consume,
        owner="example",
        generation=generation,
    )
    gate.publish(generation)
    event = NameChanged(tenant_id=uuid4(), correlation_id="durable-drain", name="name")
    assert len(events.delivery_subscribers(event)) == 1
    async with gate.admit(generation):
        drain = asyncio.create_task(gate.close_and_drain(generation, timeout_seconds=1))
        await asyncio.sleep(0)
        with pytest.raises(DeliveryUnavailableError):
            events.delivery_subscribers(event)
    await drain


def test_durable_subscriber_survives_removal_and_clean_reenable() -> None:
    gate = ContributionGate()
    old_generation = gate.reserve("example")
    events = EventBus(gate)

    async def consume(_: NameChanged, __: EventHandlingContext) -> None:
        return None

    events.subscribe(
        NameChanged,
        "example.consumer",
        consume,
        owner="example",
        generation=old_generation,
    )
    gate.publish(old_generation)
    events.remove_owner_generation(old_generation)
    gate.discard(old_generation)
    event = NameChanged(tenant_id=uuid4(), correlation_id="durable-reenable", name="name")

    assert isinstance(
        events.decode(NameChanged.event_type, event.model_dump_json().encode()), NameChanged
    )
    with pytest.raises(DeliveryUnavailableError):
        events.delivery_subscribers(event)

    new_generation = gate.reserve("example")
    events.subscribe(
        NameChanged,
        "example.consumer",
        consume,
        owner="example",
        generation=new_generation,
    )
    with pytest.raises(DeliveryUnavailableError):
        events.delivery_subscribers(event)
    gate.publish(new_generation)
    assert len(events.delivery_subscribers(event)) == 1


def test_durable_subscriber_cannot_be_claimed_by_another_owner() -> None:
    gate = ContributionGate()
    generation = gate.reserve("example")
    events = EventBus(gate)

    async def consume(_: NameChanged, __: EventHandlingContext) -> None:
        return None

    events.subscribe(
        NameChanged,
        "shared.consumer",
        consume,
        owner="example",
        generation=generation,
    )
    gate.publish(generation)
    events.remove_owner_generation(generation)
    gate.discard(generation)

    with pytest.raises(ConflictError, match="owned by another module"):
        events.subscribe(
            NameChanged,
            "shared.consumer",
            consume,
            owner="attacker",
            generation=gate.reserve("attacker"),
        )
