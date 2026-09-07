"""Framework-owned command, query and event contracts and dispatch."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.errors import ConflictError, NotFoundError
from businessos.persistence import PendingOutboxMessage, UnitOfWork, UnitOfWorkFactory
from businessos.security import Authorizer
from businessos.telemetry import dispatch_span


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
    trace_context: Mapping[str, str] = Field(default_factory=dict)

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
EventHandler = Callable[[DomainEvent, "EventHandlingContext"], Awaitable[None]]


@dataclass(slots=True)
class HandlingContext:
    request: RequestContext
    dependencies: RequestDependencyScope
    unit_of_work: UnitOfWork
    _events: list[DomainEvent] = field(default_factory=list[DomainEvent])

    def emit(self, event: DomainEvent) -> None:
        if self.request.tenant is None or event.tenant_id != self.request.tenant.tenant_id:
            raise ValueError("Event tenant must match the trusted request tenant")
        from businessos.telemetry import inject_trace_context

        emitted = event
        if not event.trace_context:
            emitted = event.model_copy(update={"trace_context": inject_trace_context()})
        self.unit_of_work.add_outbox(emitted.to_outbox())
        self._events.append(emitted)

    @property
    def emitted_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)


@dataclass(slots=True)
class EventHandlingContext:
    """Public, transaction-bound context for one durable event delivery."""

    request: RequestContext
    dependencies: RequestDependencyScope
    unit_of_work: UnitOfWork


@dataclass(frozen=True, slots=True)
class _OwnedHandler:
    owner: str
    handler: Handler
    generation: ContributionGeneration | None
    permission: str | None


class HandlerRegistry:
    def __init__(self, kind: str, gate: ContributionGate | None = None) -> None:
        self.kind = kind
        self._gate = gate
        self._handlers: dict[type[Message], _OwnedHandler] = {}

    def register[M: Message](
        self,
        message_type: type[M],
        owner: str,
        handler: Callable[[M, HandlingContext], Awaitable[object]],
        *,
        generation: ContributionGeneration | None = None,
        permission: str | None = None,
    ) -> None:
        if message_type in self._handlers:
            current_owner = self._handlers[message_type].owner
            raise ConflictError(
                f"{self.kind} handler for {message_type.__name__} is owned by {current_owner}"
            )
        self._handlers[message_type] = _OwnedHandler(
            owner,
            cast(Handler, handler),
            generation,
            permission,
        )

    def get(self, message: Message) -> Handler:
        registered = self._handlers.get(type(message))
        if registered is None:
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        if self._gate is not None and not self._gate.is_active(registered.generation):
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        return registered.handler

    async def invoke(self, message: Message, context: HandlingContext) -> object:
        registered = self._handlers.get(type(message))
        if registered is None:
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        if self._gate is None:
            return await registered.handler(message, context)
        async with self._gate.admit(registered.generation):
            return await registered.handler(message, context)

    def permission(self, message: Message) -> str | None:
        registered = self._handlers.get(type(message))
        if registered is None:
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        if self._gate is not None and not self._gate.is_active(registered.generation):
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        return registered.permission

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._handlers = {
            message_type: handler
            for message_type, handler in self._handlers.items()
            if handler.generation != generation
        }


@dataclass(frozen=True, slots=True)
class _OwnedEventHandler:
    owner: str
    subscriber: str
    handler: EventHandler
    generation: ContributionGeneration | None
    permission: str | None


class EventBus:
    def __init__(
        self,
        gate: ContributionGate | None = None,
        authorizer: Authorizer | None = None,
    ) -> None:
        self._gate = gate
        self._authorizer = authorizer
        self._handlers: dict[type[DomainEvent], dict[str, _OwnedEventHandler]] = {}

    def subscribe[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, EventHandlingContext], Awaitable[None]],
        *,
        owner: str | None = None,
        generation: ContributionGeneration | None = None,
        permission: str | None = None,
    ) -> None:
        handlers = self._handlers.setdefault(event_type, {})
        if subscriber in handlers:
            raise ConflictError(
                f"Event subscriber already registered: {event_type.__name__}/{subscriber}"
            )
        handlers[subscriber] = _OwnedEventHandler(
            owner or subscriber,
            subscriber,
            cast(EventHandler, handler),
            generation,
            permission,
        )

    def subscribers(self, event: DomainEvent) -> tuple[_OwnedEventHandler, ...]:
        handlers = self._handlers.get(type(event), {})
        return tuple(
            handlers[name]
            for name in sorted(handlers)
            if self._gate is None or self._gate.is_active(handlers[name].generation)
        )

    async def authorize(self, context: RequestContext, permission: str | None) -> None:
        await self._authorize(context, permission)

    async def invoke(
        self,
        registered: _OwnedEventHandler,
        event: DomainEvent,
        context: EventHandlingContext,
    ) -> None:
        if self._gate is None:
            await registered.handler(event, context)
            return
        async with self._gate.admit(registered.generation):
            await registered.handler(event, context)

    async def _authorize(self, context: RequestContext, permission: str | None) -> None:
        if permission is None:
            return
        if self._authorizer is None:
            raise RuntimeError("Authorized event dispatch requires an authorizer")
        await self._authorizer.require(context, permission)

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        for event_type in tuple(self._handlers):
            handlers = self._handlers[event_type]
            self._handlers[event_type] = {
                subscriber: handler
                for subscriber, handler in handlers.items()
                if handler.generation != generation
            }
            if not self._handlers[event_type]:
                del self._handlers[event_type]


class MessageDispatcher:
    """Enforce Unit of Work boundaries around commands and queries."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        event_bus: EventBus,
        gate: ContributionGate | None = None,
        authorizer: Authorizer | None = None,
    ) -> None:
        self.commands = HandlerRegistry("command", gate)
        self.queries = HandlerRegistry("query", gate)
        self.events = event_bus
        self._unit_of_work_factory = unit_of_work_factory
        self._authorizer = authorizer

    async def command(
        self,
        message: Command,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> object:
        with dispatch_span("command", type(message).__name__):
            await self._authorize(context, self.commands.permission(message))
            unit_of_work = self._unit_of_work(context)
            async with unit_of_work:
                handling = HandlingContext(context, dependencies, unit_of_work)
                result = await self.commands.invoke(message, handling)
                await unit_of_work.commit()
            return result

    async def query(
        self,
        message: Query,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> object:
        with dispatch_span("query", type(message).__name__):
            await self._authorize(context, self.queries.permission(message))
            unit_of_work = self._unit_of_work(context)
            async with unit_of_work:
                handling = HandlingContext(context, dependencies, unit_of_work)
                return await self.queries.invoke(message, handling)

    async def _authorize(self, context: RequestContext, permission: str | None) -> None:
        if permission is None:
            return
        if self._authorizer is None:
            raise RuntimeError("Authorized message dispatch requires an authorizer")
        await self._authorizer.require(context, permission)

    def _unit_of_work(self, context: RequestContext) -> UnitOfWork:
        if context.tenant is None:
            return self._unit_of_work_factory.system()
        return self._unit_of_work_factory.for_tenant(context.tenant)
