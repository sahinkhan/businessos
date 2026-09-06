"""Framework-owned command, query and event contracts and dispatch."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.errors import ConflictError, NotFoundError
from businessos.persistence import PendingOutboxMessage, UnitOfWork, UnitOfWorkFactory


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)


class Command(Message):
    pass


class Query(Message):
    pass


class DomainEvent(Message):
    event_type: ClassVar[str]
    schema_version: ClassVar[int] = 1

    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str
    causation_id: str | None = None

    def to_outbox(self) -> PendingOutboxMessage:
        return PendingOutboxMessage(
            event_id=self.event_id,
            tenant_id=self.tenant_id,
            event_type=self.event_type,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            payload=self.model_dump(mode="json"),
        )


Handler = Callable[[Message, "HandlingContext"], Awaitable[object]]
EventHandler = Callable[[DomainEvent, RequestContext, RequestDependencyScope], Awaitable[None]]


@dataclass(slots=True)
class HandlingContext:
    request: RequestContext
    dependencies: RequestDependencyScope
    unit_of_work: UnitOfWork
    _events: list[DomainEvent] = field(default_factory=list[DomainEvent])

    def emit(self, event: DomainEvent) -> None:
        if self.request.tenant is None or event.tenant_id != self.request.tenant.tenant_id:
            raise ValueError("Event tenant must match the trusted request tenant")
        self.unit_of_work.add_outbox(event.to_outbox())
        self._events.append(event)

    @property
    def emitted_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)


class HandlerRegistry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._handlers: dict[type[Message], tuple[str, Handler]] = {}

    def register[M: Message](
        self,
        message_type: type[M],
        owner: str,
        handler: Callable[[M, HandlingContext], Awaitable[object]],
    ) -> None:
        if message_type in self._handlers:
            current_owner = self._handlers[message_type][0]
            raise ConflictError(
                f"{self.kind} handler for {message_type.__name__} is owned by {current_owner}"
            )
        self._handlers[message_type] = (owner, cast(Handler, handler))

    def get(self, message: Message) -> Handler:
        registered = self._handlers.get(type(message))
        if registered is None:
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        return registered[1]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], dict[str, EventHandler]] = {}

    def subscribe[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, RequestContext, RequestDependencyScope], Awaitable[None]],
    ) -> None:
        handlers = self._handlers.setdefault(event_type, {})
        if subscriber in handlers:
            raise ConflictError(
                f"Event subscriber already registered: {event_type.__name__}/{subscriber}"
            )
        handlers[subscriber] = cast(EventHandler, handler)

    async def publish(
        self,
        event: DomainEvent,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> None:
        handlers = self._handlers.get(type(event), {})
        for subscriber in sorted(handlers):
            await handlers[subscriber](event, context, dependencies)


class MessageDispatcher:
    """Enforce Unit of Work boundaries around commands and queries."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory, event_bus: EventBus) -> None:
        self.commands = HandlerRegistry("command")
        self.queries = HandlerRegistry("query")
        self.events = event_bus
        self._unit_of_work_factory = unit_of_work_factory

    async def command(
        self,
        message: Command,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> object:
        unit_of_work = self._unit_of_work(context)
        async with unit_of_work:
            handling = HandlingContext(context, dependencies, unit_of_work)
            result = await self.commands.get(message)(message, handling)
            await unit_of_work.commit()
        for event in handling.emitted_events:
            await self.events.publish(event, context, dependencies)
        return result

    async def query(
        self,
        message: Query,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> object:
        unit_of_work = self._unit_of_work(context)
        async with unit_of_work:
            handling = HandlingContext(context, dependencies, unit_of_work)
            return await self.queries.get(message)(message, handling)

    def _unit_of_work(self, context: RequestContext) -> UnitOfWork:
        if context.tenant is None:
            return self._unit_of_work_factory.system()
        return self._unit_of_work_factory.for_tenant(context.tenant)
