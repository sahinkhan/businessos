"""Private bounded admission before protected database checkout."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from businessos.errors import ConfigurationError, ProtectedDatabaseCapacityError


@dataclass(eq=False, slots=True)
class _Ticket:
    keys: frozenset[str]


class _KeyedAdmission:
    """FIFO among overlapping key sets; independent keys can progress.

    Tickets exist only while waiting/admitted, with a hard total bound. No
    database authority is stored here or exposed to modules/SDK dependencies.
    """

    def __init__(self, *, timeout: float, limit: int = 4096) -> None:
        self._timeout = timeout
        self._limit = limit
        self._condition = asyncio.Condition()
        self._tickets: list[_Ticket] = []
        self._closed = False

    @asynccontextmanager
    async def admit(self, keys: frozenset[str]) -> AsyncGenerator[None]:
        ticket = _Ticket(keys)
        async with self._condition:
            if self._closed:
                raise ConfigurationError("Protected database admission is closed")
            if len(self._tickets) >= self._limit:
                raise ProtectedDatabaseCapacityError()
            self._tickets.append(ticket)
            self._condition.notify_all()
        try:
            try:
                async with asyncio.timeout(self._timeout):
                    async with self._condition:
                        while True:
                            if self._closed:
                                raise ConfigurationError("Protected database admission is closed")
                            prior = self._tickets[: self._tickets.index(ticket)]
                            if not any(other.keys & keys for other in prior):
                                break
                            await self._condition.wait()
            except TimeoutError:
                raise ProtectedDatabaseCapacityError() from None
            yield
        finally:
            # Repeated request cancellation must not interrupt ticket cleanup.
            cleanup = asyncio.create_task(self._remove(ticket))
            cancellation: asyncio.CancelledError | None = None
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError as error:
                    cancellation = error
            cleanup.result()
            if cancellation is not None:
                raise cancellation

    async def _remove(self, ticket: _Ticket) -> None:
        async with self._condition:
            self._tickets.remove(ticket)
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


def internal_database_admission(*, timeout: float) -> _KeyedAdmission:
    """Private kernel composition; not registered in SDK or module DI."""
    return _KeyedAdmission(timeout=timeout)
