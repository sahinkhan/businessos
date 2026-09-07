"""Framework-owned command, query and event contracts and dispatch."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration, ContributionState
from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.errors import ConflictError, DeliveryUnavailableError, NotFoundError
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
        return self.resolve(message).handler

    def resolve(self, message: Message) -> _OwnedHandler:
        """Capture one active registration for authorization and invocation."""
        registered = self._handlers.get(type(message))
        if registered is None:
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        if self._gate is not None and not self._gate.is_active(registered.generation):
            raise NotFoundError(f"No {self.kind} handler for {type(message).__name__}")
        return registered

    @asynccontextmanager
    async def admitted(self, registered: _OwnedHandler) -> AsyncGenerator[None]:
        """Hold admission for the exact captured generation across dispatch."""
        if self._gate is None:
            yield
            return
        async with self._gate.admit(registered.generation):
            yield

    async def invoke_registered(
        self,
        registered: _OwnedHandler,
        message: Message,
        context: HandlingContext,
    ) -> object:
        return await registered.handler(message, context)

    async def invoke(self, message: Message, context: HandlingContext) -> object:
        registered = self.resolve(message)
        async with self.admitted(registered):
            return await self.invoke_registered(registered, message, context)

    def permission(self, message: Message) -> str | None:
        return self.resolve(message).permission

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


@dataclass(frozen=True, slots=True)
class DurableSubscriberDeclaration:
    event_type: str
    subscriber: str
    owner: str


class EventBus:
    def __init__(
        self,
        gate: ContributionGate | None = None,
        authorizer: Authorizer | None = None,
    ) -> None:
        self._gate = gate
        self._authorizer = authorizer
        self._handlers: dict[type[DomainEvent], dict[str, _OwnedEventHandler]] = {}
        self._event_types: dict[str, type[DomainEvent]] = {}
        self._durable_subscriber_owners: dict[str, dict[str, str]] = {}

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
        current_type = self._event_types.get(event_type.event_type)
        if current_type is not None and current_type is not event_type:
            raise ConflictError(f"Event type is already registered: {event_type.event_type}")
        self._event_types[event_type.event_type] = event_type
        resolved_owner = owner or subscriber
        durable_owner = self._durable_subscriber_owners.get(event_type.event_type, {}).get(
            subscriber
        )
        if durable_owner is not None and durable_owner != resolved_owner:
            raise ConflictError(
                f"Durable event subscriber is owned by another module: "
                f"{event_type.event_type}/{subscriber}"
            )
        handlers = self._handlers.setdefault(event_type, {})
        if subscriber in handlers:
            raise ConflictError(
                f"Event subscriber already registered: {event_type.__name__}/{subscriber}"
            )
        handlers[subscriber] = _OwnedEventHandler(
            resolved_owner,
            subscriber,
            cast(EventHandler, handler),
            generation,
            permission,
        )

    def decode(
        self,
        event_type: str,
        payload: bytes,
        *,
        schema_version: int | None = None,
    ) -> DomainEvent:
        registered = self._event_types.get(event_type)
        if registered is None:
            raise NotFoundError(f"Unknown event type: {event_type}")
        if schema_version is not None and schema_version != registered.schema_version:
            raise DeliveryUnavailableError(
                f"Unsupported event schema version: {event_type}/{schema_version}"
            )
        return registered.model_validate_json(payload)

    def subscribers(self, event: DomainEvent) -> tuple[_OwnedEventHandler, ...]:
        handlers = self._handlers.get(type(event), {})
        return tuple(
            handlers[name]
            for name in sorted(handlers)
            if self._gate is None or self._gate.is_active(handlers[name].generation)
        )

    def delivery_subscribers(self, event: DomainEvent) -> tuple[_OwnedEventHandler, ...]:
        """Return the complete active obligation set or require broker redelivery."""
        handlers = self._handlers.get(type(event), {})
        obligated = set(self._durable_subscriber_owners.get(event.event_type, {}))
        obligated.update(handlers)
        active = self.subscribers(event)
        if obligated - {handler.subscriber for handler in active}:
            raise DeliveryUnavailableError("Durable event subscriber is temporarily unavailable")
        return active

    @asynccontextmanager
    async def admit_delivery(
        self,
        event: DomainEvent,
    ) -> AsyncGenerator[tuple[_OwnedEventHandler, ...]]:
        """Hold one atomic admission lease for the complete durable subscriber set."""
        subscribers = self.delivery_subscribers(event)
        if self._gate is None:
            yield subscribers
            return
        async with self._gate.admit_many(item.generation for item in subscribers):
            yield subscribers

    def subscriber_declarations(self) -> tuple[DurableSubscriberDeclaration, ...]:
        return tuple(
            DurableSubscriberDeclaration(event_type.event_type, subscriber, handler.owner)
            for event_type, handlers in sorted(
                self._handlers.items(), key=lambda item: item[0].event_type
            )
            for subscriber, handler in sorted(handlers.items())
        )

    def bind_durable_subscribers(
        self,
        declarations: Iterable[DurableSubscriberDeclaration],
    ) -> None:
        merged = {
            event_type: dict(owners)
            for event_type, owners in self._durable_subscriber_owners.items()
        }
        for declaration in declarations:
            owners = merged.setdefault(declaration.event_type, {})
            existing = owners.get(declaration.subscriber)
            if existing is not None and existing != declaration.owner:
                raise ConflictError(
                    "Durable event subscriber ownership changed: "
                    f"{declaration.event_type}/{declaration.subscriber}"
                )
            for event_type, handlers in self._handlers.items():
                if event_type.event_type != declaration.event_type:
                    continue
                current = handlers.get(declaration.subscriber)
                if current is not None and current.owner != declaration.owner:
                    raise ConflictError(
                        "Durable event subscriber is owned by another module: "
                        f"{declaration.event_type}/{declaration.subscriber}"
                    )
            owners[declaration.subscriber] = declaration.owner
        self._durable_subscriber_owners = merged

    async def authorize(self, context: RequestContext, permission: str | None) -> None:
        await self._authorize(context, permission)

    @asynccontextmanager
    async def admitted(self, registered: _OwnedEventHandler) -> AsyncGenerator[None]:
        if self._gate is None:
            yield
            return
        async with self._gate.admit(registered.generation):
            yield

    async def invoke(
        self,
        registered: _OwnedEventHandler,
        event: DomainEvent,
        context: EventHandlingContext,
    ) -> None:
        async with self.admitted(registered):
            await registered.handler(event, context)

    async def invoke_registered(
        self,
        registered: _OwnedEventHandler,
        event: DomainEvent,
        context: EventHandlingContext,
    ) -> None:
        await registered.handler(event, context)

    async def _authorize(self, context: RequestContext, permission: str | None) -> None:
        if permission is None:
            return
        if self._authorizer is None:
            raise RuntimeError("Authorized event dispatch requires an authorizer")
        await self._authorizer.require(context, permission)

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        generation_was_published = (
            self._gate is not None and self._gate.state(generation) is not ContributionState.STAGED
        )
        for event_type in tuple(self._handlers):
            handlers = self._handlers[event_type]
            if generation_was_published:
                durable_owners = self._durable_subscriber_owners.setdefault(
                    event_type.event_type, {}
                )
                for handler in handlers.values():
                    if handler.generation == generation:
                        durable_owners[handler.subscriber] = handler.owner
            self._handlers[event_type] = {
                subscriber: handler
                for subscriber, handler in handlers.items()
                if handler.generation != generation
            }
            if not self._handlers[event_type]:
                del self._handlers[event_type]
                if not self._durable_subscriber_owners.get(event_type.event_type):
                    self._event_types.pop(event_type.event_type, None)


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
            registered = self.commands.resolve(message)
            async with self.commands.admitted(registered):
                await self._authorize(context, registered.permission)
                unit_of_work = self._unit_of_work(context)
                async with unit_of_work:
                    handling = HandlingContext(context, dependencies, unit_of_work)
                    result = await self.commands.invoke_registered(registered, message, handling)
                    await unit_of_work.commit()
                return result

    async def query(
        self,
        message: Query,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> object:
        with dispatch_span("query", type(message).__name__):
            registered = self.queries.resolve(message)
            async with self.queries.admitted(registered):
                await self._authorize(context, registered.permission)
                unit_of_work = self._unit_of_work(context)
                async with unit_of_work:
                    handling = HandlingContext(context, dependencies, unit_of_work)
                    return await self.queries.invoke_registered(registered, message, handling)

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
