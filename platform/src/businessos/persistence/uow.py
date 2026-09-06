"""Explicit framework-owned Unit of Work and transaction boundaries."""

from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, Protocol, Self

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.base import Executable

from businessos.context import TenantContext
from businessos.errors import ConfigurationError
from businessos.persistence.contracts import TransactionalPersistence
from businessos.persistence.models import OutboxMessage
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
        await self.session.begin()
        if self.tenant_context is not None:
            await self.session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(self.tenant_context.tenant_id)},
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is not None or not self._committed:
                await self.session.rollback()
        finally:
            await self.session.close()
            self.session = None

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

    def _require_session(self) -> AsyncSession:
        if self.session is None:
            raise ConfigurationError("Unit of Work is not active")
        return self.session


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
