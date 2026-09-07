"""Standalone durable event delivery process owned by the BusinessOS framework."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.eventing import OutboxPublisher
from businessos.messages import DurableSubscriberDeclaration
from businessos.modules import BusinessOSModule, discover_modules
from businessos.persistence import (
    Database,
    EventSubscriberObligation,
    SQLAlchemyUnitOfWorkFactory,
)
from businessos.providers import (
    BrokerEvent,
    DurableEventBroker,
    EventSubscription,
    NatsJetStreamPublisher,
    ObjectStorageProvider,
    PermanentDeliveryError,
    S3ObjectStorageProvider,
)
from businessos.secure_settings import SafeSettings
from businessos.security import Authorizer


class EventWorkerSettings(SafeSettings):
    """Credentials and identity loaded only by the standalone event worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BOS_EVENT_WORKER_",
        extra="ignore",
    )

    tenant_database_urls: dict[UUID, str] = Field(default_factory=dict, repr=False, exclude=True)
    runtime_database_url: str = Field(repr=False, exclude=True)
    operations_database_url: str = Field(repr=False, exclude=True)
    nats_url: str = Field(default="nats://localhost:4222", repr=False, exclude=True)
    installation_id: UUID
    principal_id: UUID
    permissions: str = ""
    durable_name: str = "businessos-events"
    publish_interval_seconds: float = Field(default=0.25, gt=0)
    publish_batch_size: int = Field(default=100, ge=1, le=10_000)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0)
    process_shutdown_timeout_seconds: float = Field(default=60.0, gt=0)
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = Field(default=None, repr=False, exclude=True)
    s3_region_name: str | None = None
    s3_access_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_secret_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_provision_bucket: bool = False

    @model_validator(mode="after")
    def validate_database_roles_and_storage(self) -> "EventWorkerSettings":
        for value in (self.runtime_database_url, self.operations_database_url):
            if not value.startswith("postgresql+psycopg://"):
                raise ValueError("event worker database URLs must use postgresql+psycopg")
        runtime_role = make_url(self.runtime_database_url).username
        operations_role = make_url(self.operations_database_url).username
        if runtime_role is None or operations_role is None or runtime_role == operations_role:
            raise ValueError("runtime and operations database roles must be separate")
        storage_values = (self.s3_bucket, self.s3_access_key, self.s3_secret_key)
        if any(storage_values) and not all(storage_values):
            raise ValueError("S3 bucket, access key and secret key must be configured together")
        return self

    @property
    def allowed_permissions(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.permissions.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class _WorkerContextResolver:
    installation_id: UUID
    principal_id: UUID

    def resolve(self, event: BrokerEvent, tenant_id: UUID, correlation_id: str) -> RequestContext:
        traceparent = event.headers.get("traceparent", "")
        trace_parts = traceparent.split("-")
        trace_id = trace_parts[1] if len(trace_parts) == 4 else ""
        return RequestContext(
            correlation_id=correlation_id,
            trace_id=trace_id,
            tenant=TenantContext(
                installation_id=self.installation_id,
                tenant_id=tenant_id,
                principal_id=self.principal_id,
                authentication_strength="service-account",
            ),
        )


@dataclass(frozen=True, slots=True)
class _WorkerPermissionPolicy:
    principal_id: UUID
    permissions: frozenset[str]

    async def is_allowed(
        self,
        principal_id: UUID,
        tenant: TenantContext,
        permission: str,
    ) -> bool:
        return principal_id == self.principal_id and permission in self.permissions


class _CommonBrokerEvent(BaseModel):
    """Validate transport-neutral event fields before contract lookup."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    tenant_id: UUID
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None = None
    trace_context: Mapping[str, str] = Field(default_factory=dict)


class EventWorker:
    """Publish committed outbox rows and transactionally consume JetStream events."""

    def __init__(
        self,
        *,
        application: BusinessOSApplication,
        operations_database: Database,
        broker: DurableEventBroker,
        context_resolver: _WorkerContextResolver,
        durable_name: str,
        publish_interval_seconds: float,
        publish_batch_size: int,
        shutdown_timeout_seconds: float,
        subject_prefix: str = "businessos.events",
    ) -> None:
        if application.runtime is None:
            raise RuntimeError("Event worker requires a framework runtime")
        self.application = application
        self._operations_database = operations_database
        self._broker = broker
        self._context_resolver = context_resolver
        self._durable_name = durable_name
        self._publish_interval_seconds = publish_interval_seconds
        self._publish_batch_size = publish_batch_size
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._subject_prefix = subject_prefix
        self._operations_uow = SQLAlchemyUnitOfWorkFactory(
            operations_database.sessions,
            system_sessions=operations_database.sessions,
        )
        self._publisher = OutboxPublisher(
            self._operations_uow,
            broker,
            subject_prefix=subject_prefix,
        )
        self._subscription: EventSubscription | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._stop_publisher = asyncio.Event()
        self._started = False
        self._lifecycle_lock = asyncio.Lock()
        self._subscriber_sync_lock = asyncio.Lock()
        self._logger = logging.getLogger("businessos.event-worker")

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            await self._operations_database.readiness()
            try:
                await self.application.startup()
                await self._synchronize_subscriber_obligations()
                self._subscription = await self._broker.subscribe(
                    f"{self._subject_prefix}.tenant.>",
                    self._durable_name,
                    self._consume_delivery,
                )
                self._stop_publisher.clear()
                self._publisher_task = asyncio.create_task(
                    self._publish_loop(), name="businessos-outbox-publisher"
                )
            except BaseException as startup_error:
                cleanup_error, _ = await self._run_owned_cleanup()
                if cleanup_error is not None:
                    raise BaseExceptionGroup(
                        "Event worker startup and cleanup failed",
                        [startup_error, cleanup_error],
                    ) from None
                raise
            self._started = True

    async def readiness(self) -> None:
        if not self._started or self._publisher_task is None:
            raise RuntimeError("Event worker is not running")
        if self._publisher_task.done():
            self._publisher_task.result()
            raise RuntimeError("Outbox publisher stopped")
        await self.application.readiness()
        await self._operations_database.readiness()
        await self._broker.readiness()

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if not self._started and self._subscription is None and self._publisher_task is None:
                await self._operations_database.close()
                return
            cleanup_error, cancellation_count = await self._run_owned_cleanup()
            self._started = False
            if cleanup_error is not None:
                raise cleanup_error
            if cancellation_count:
                raise asyncio.CancelledError

    async def _run_owned_cleanup(self) -> tuple[BaseException | None, int]:
        cleanup_task = asyncio.create_task(self._cleanup(), name="businessos-event-worker-cleanup")
        cancellation_count = 0
        current = asyncio.current_task()
        if current is not None:
            while current.cancelling():
                cancellation_count += 1
                current.uncancel()
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancellation_count += 1
                if current is not None:
                    while current.cancelling():
                        current.uncancel()
        try:
            cleanup_task.result()
        except BaseException as exc:
            return exc, cancellation_count
        return None, cancellation_count

    async def _cleanup(self) -> None:
        errors: list[BaseException] = []
        pending: list[asyncio.Task[None]] = []
        self._stop_publisher.set()
        if self._subscription is not None:
            step_errors, pending_task = await self._start_cleanup_step(
                self._subscription.close,
                label="event subscription",
            )
            errors.extend(step_errors)
            if pending_task is not None:
                pending.append(pending_task)
        if self._publisher_task is not None:
            step_errors, pending_task = await self._bound_and_cancel_task(
                self._publisher_task,
                label="outbox publisher",
            )
            errors.extend(step_errors)
            if pending_task is not None:
                pending.append(pending_task)
        step_errors, pending_task = await self._start_cleanup_step(
            self.application.shutdown,
            label="application",
        )
        errors.extend(step_errors)
        if pending_task is not None:
            pending.append(pending_task)
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except BaseException as exc:
                errors.append(exc)
        final_errors, final_pending = await self._start_cleanup_step(
            self._operations_database.close,
            label="operations database",
        )
        errors.extend(final_errors)
        if final_pending is not None:
            try:
                await final_pending
            except asyncio.CancelledError:
                pass
            except BaseException as exc:
                errors.append(exc)
        self._subscription = None
        self._publisher_task = None
        if errors:
            raise BaseExceptionGroup("Event worker cleanup failed", errors)

    async def _start_cleanup_step(
        self,
        cleanup: Callable[[], Awaitable[None]],
        *,
        label: str,
    ) -> tuple[list[BaseException], asyncio.Task[None] | None]:
        async def run() -> None:
            await cleanup()

        task = asyncio.create_task(run(), name=f"businessos-{label.replace(' ', '-')}-cleanup")
        return await self._bound_and_cancel_task(task, label=label)

    async def _bound_and_cancel_task(
        self,
        task: asyncio.Task[None],
        *,
        label: str,
    ) -> tuple[list[BaseException], asyncio.Task[None] | None]:
        done, _ = await asyncio.wait((task,), timeout=self._shutdown_timeout_seconds)
        if task in done:
            try:
                task.result()
            except BaseException as exc:
                return [exc], None
            return [], None

        errors: list[BaseException] = [TimeoutError(f"{label} cleanup timed out")]
        for _ in range(8):
            if task.done():
                break
            task.cancel()
            await asyncio.sleep(0)
        if not task.done():
            return errors, task
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except BaseException as exc:
            errors.append(exc)
        return errors, None

    async def _publish_loop(self) -> None:
        while not self._stop_publisher.is_set():
            try:
                await self._synchronize_subscriber_obligations()
                published = await self._publisher.publish_batch(self._publish_batch_size)
            except Exception as exc:
                self._logger.warning(
                    "Outbox publication cycle failed",
                    extra={"error_type": type(exc).__name__},
                )
                published = 0
            if published >= self._publish_batch_size:
                continue
            try:
                await asyncio.wait_for(
                    self._stop_publisher.wait(), timeout=self._publish_interval_seconds
                )
            except TimeoutError:
                pass

    async def _consume_delivery(self, delivery: BrokerEvent) -> None:
        runtime = self.application.runtime
        if runtime is None:  # pragma: no cover - constructor enforces this
            raise RuntimeError("Event worker runtime is unavailable")
        try:
            event_type = self._required_header(delivery, "event-type")
            tenant_id = UUID(self._required_header(delivery, "tenant-id"))
            event_id = UUID(self._required_header(delivery, "event-id"))
            schema_version = int(self._required_header(delivery, "schema-version"))
            correlation_id = self._required_header(delivery, "correlation-id")
            expected_subject = f"{self._subject_prefix}.tenant.{tenant_id}.{event_type}"
            if delivery.subject != expected_subject:
                raise ValueError("event subject does not match its trusted envelope")
            if schema_version < 1:
                raise ValueError("event schema version must be positive")
            common_event = _CommonBrokerEvent.model_validate_json(delivery.payload)
            if (
                common_event.event_id != event_id
                or common_event.tenant_id != tenant_id
                or common_event.correlation_id != correlation_id
            ):
                raise ValueError("event payload does not match its trusted envelope")
            event = runtime.events.decode(
                event_type,
                delivery.payload,
                schema_version=schema_version,
            )
            if (
                event.event_id != event_id
                or event.tenant_id != tenant_id
                or event.schema_version != schema_version
                or event.correlation_id != correlation_id
            ):
                raise ValueError("event payload does not match its trusted envelope")
        except (LookupError, TypeError, ValueError) as exc:
            raise PermanentDeliveryError("Invalid event envelope") from exc

        await self._synchronize_subscriber_obligations()
        context = self._context_resolver.resolve(delivery, tenant_id, correlation_id)
        async with self.application.container.request_scope() as dependencies:
            await runtime.event_consumer.consume(event, context, dependencies)

    async def _synchronize_subscriber_obligations(self) -> None:
        runtime = self.application.runtime
        if runtime is None:  # pragma: no cover - constructor enforces this
            raise RuntimeError("Event worker runtime is unavailable")
        async with self._subscriber_sync_lock:
            declarations = runtime.events.subscriber_declarations()
            async with self._operations_uow.system() as unit_of_work:
                if declarations:
                    await unit_of_work.persistence.execute(
                        insert(EventSubscriberObligation)
                        .values(
                            [
                                {
                                    "event_type": item.event_type,
                                    "subscriber": item.subscriber,
                                    "owner": item.owner,
                                }
                                for item in declarations
                            ]
                        )
                        .on_conflict_do_nothing(index_elements=["event_type", "subscriber"])
                    )
                result = await unit_of_work.persistence.execute(
                    select(EventSubscriberObligation).order_by(
                        EventSubscriberObligation.event_type,
                        EventSubscriberObligation.subscriber,
                    )
                )
                runtime.events.bind_durable_subscribers(
                    DurableSubscriberDeclaration(item.event_type, item.subscriber, item.owner)
                    for item in result.scalars()
                )
                await unit_of_work.commit()

    @staticmethod
    def _required_header(delivery: BrokerEvent, name: str) -> str:
        value = delivery.headers.get(name)
        if value is None or not value.strip():
            raise LookupError(f"Missing required event header: {name}")
        return value


def create_event_worker(
    settings: EventWorkerSettings,
    *,
    modules: Iterable[BusinessOSModule] | None = None,
    broker: DurableEventBroker | None = None,
    object_storage: ObjectStorageProvider | None = None,
) -> EventWorker:
    """Compose the isolated worker; operational credentials never enter the web app."""
    resolved_broker = broker or NatsJetStreamPublisher((settings.nats_url,))
    resolved_storage = object_storage
    if resolved_storage is None and settings.s3_bucket is not None:
        resolved_storage = S3ObjectStorageProvider(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region_name,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            provision_bucket=settings.s3_provision_bucket,
        )
    providers: dict[str, object] = {"event-publisher": resolved_broker}
    if resolved_storage is not None:
        providers["object-storage"] = resolved_storage
    application = create_application(
        Settings(
            database_url=settings.runtime_database_url,
            tenant_database_urls=settings.tenant_database_urls,
            shutdown_timeout_seconds=settings.shutdown_timeout_seconds,
        ),
        modules=tuple(discover_modules()) if modules is None else modules,
        authorizer=Authorizer(
            _WorkerPermissionPolicy(settings.principal_id, settings.allowed_permissions)
        ),
        infrastructure_providers=providers,
    )
    operations_database = Database(Settings(database_url=settings.operations_database_url))
    return EventWorker(
        application=application,
        operations_database=operations_database,
        broker=resolved_broker,
        context_resolver=_WorkerContextResolver(
            settings.installation_id,
            settings.principal_id,
        ),
        durable_name=settings.durable_name,
        publish_interval_seconds=settings.publish_interval_seconds,
        publish_batch_size=settings.publish_batch_size,
        shutdown_timeout_seconds=settings.shutdown_timeout_seconds,
    )
