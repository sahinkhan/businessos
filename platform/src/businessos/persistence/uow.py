"""Explicit framework-owned Unit of Work and transaction boundaries."""

import asyncio
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.base import Executable

from businessos.context import TenantContext
from businessos.errors import ConfigurationError
from businessos.persistence.contracts import TransactionalPersistence
from businessos.persistence.models import InboxReceipt, OutboxMessage
from businessos.persistence.outbox import PendingOutboxMessage

SessionFactory = Callable[[], AsyncSession]


class UnitOfWork(Protocol):
    @property
    def persistence(self) -> TransactionalPersistence: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    def add_outbox(self, message: PendingOutboxMessage) -> None: ...

    async def claim_inbox(self, *, consumer: str, event_id: UUID, tenant_id: UUID) -> bool: ...


class UnitOfWorkFactory(Protocol):
    def for_tenant(self, context: TenantContext) -> UnitOfWork: ...

    def system(self) -> UnitOfWork: ...


class SQLAlchemyUnitOfWork:
    """One SQLAlchemy session and transaction for one command/query operation."""

    def __init__(
        self,
        sessions: SessionFactory,
        tenant_context: TenantContext | None,
    ) -> None:
        self._sessions = sessions
        self.tenant_context = tenant_context
        self.session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        if self.session is not None:
            raise ConfigurationError("Unit of Work cannot be entered twice")
        self.session = self._sessions()
        try:
            await self.session.begin()
            if self.tenant_context is not None:
                await self.session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(self.tenant_context.tenant_id)},
                )
        except BaseException as entry_error:
            cleanup_errors, _ = await self._finish_session(rollback=True)
            if cleanup_errors:
                raise BaseExceptionGroup(
                    "Unit of Work entry and cleanup failed",
                    [entry_error, *cleanup_errors],
                ) from None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        cleanup_errors, cancellation_count = await self._finish_session(
            rollback=exc_type is not None or not self._committed
        )
        if cleanup_errors:
            errors: list[BaseException] = []
            if exc_value is not None:
                errors.append(exc_value)
            errors.extend(cleanup_errors)
            raise BaseExceptionGroup("Unit of Work cleanup failed", errors) from None
        if cancellation_count and exc_type is None:
            raise asyncio.CancelledError

    async def commit(self) -> None:
        session = self._require_session()
        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        session = self._require_session()
        await session.rollback()

    @property
    def persistence(self) -> TransactionalPersistence:
        return SQLAlchemyTransactionalPersistence(self._require_session())

    def add_outbox(self, message: PendingOutboxMessage) -> None:
        session = self._require_session()
        session.add(
            OutboxMessage(
                id=message.event_id,
                tenant_id=message.tenant_id,
                event_type=message.event_type,
                schema_version=message.schema_version,
                occurred_at=message.occurred_at,
                correlation_id=message.correlation_id,
                causation_id=message.causation_id,
                payload=message.payload,
            )
        )

    async def claim_inbox(self, *, consumer: str, event_id: UUID, tenant_id: UUID) -> bool:
        from sqlalchemy.dialects.postgresql import insert

        statement = (
            insert(InboxReceipt)
            .values(consumer=consumer, event_id=event_id, tenant_id=tenant_id)
            .on_conflict_do_nothing(index_elements=["tenant_id", "consumer", "event_id"])
            .returning(InboxReceipt.event_id)
        )
        return await self._require_session().scalar(statement) is not None

    def _require_session(self) -> AsyncSession:
        if self.session is None:
            raise ConfigurationError("Unit of Work is not active")
        return self.session

    async def _finish_session(self, *, rollback: bool) -> tuple[list[BaseException], int]:
        session = self.session
        if session is None:
            return [], 0

        async def cleanup() -> list[BaseException]:
            errors: list[BaseException] = []
            if rollback:
                try:
                    await session.rollback()
                except BaseException as exc:
                    errors.append(exc)
            try:
                await session.close()
            except BaseException as exc:
                errors.append(exc)
            return errors

        cleanup_task = asyncio.create_task(cleanup(), name="businessos-uow-cleanup")
        cancellation_count = 0
        current = asyncio.current_task()
        if current is not None:
            while current.cancelling():
                current.uncancel()
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancellation_count += 1
                if current is not None:
                    while current.cancelling():
                        current.uncancel()
        self.session = None
        return cleanup_task.result(), cancellation_count


class SQLAlchemyTransactionalPersistence:
    """Restricted adapter over the Unit-of-Work-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        statement: Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Result[Any]:
        if parameters is None:
            return await self._session.execute(statement)
        return await self._session.execute(statement, parameters)

    async def flush(self) -> None:
        await self._session.flush()


class SQLAlchemyUnitOfWorkFactory:
    def __init__(
        self,
        sessions: SessionFactory,
        *,
        system_sessions: SessionFactory | None = None,
    ) -> None:
        self._sessions = sessions
        self._system_sessions = system_sessions

    def for_tenant(self, context: TenantContext) -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(self._sessions, context)

    def system(self) -> SQLAlchemyUnitOfWork:
        if self._system_sessions is None:
            raise ConfigurationError(
                "System Unit of Work requires an explicitly configured operational database role"
            )
        return SQLAlchemyUnitOfWork(self._system_sessions, None)
