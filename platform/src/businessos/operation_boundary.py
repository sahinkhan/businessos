"""Framework-owned completion guards and admission lifetime, without commit authority."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any
from weakref import ReferenceType, ref

from businessos.errors import ConfigurationError


class OperationBoundary:
    """The dispatcher alone completes an operation, after all handler work."""

    def __init__(self) -> None:
        self.resources = AsyncExitStack()
        self.guards: list[Callable[[], AbstractAsyncContextManager[None]]] = []
        self.completed = False
        self.retained = 0
        self.identities: set[int] = set()

    async def __aenter__(self) -> OperationBoundary:
        return self

    async def __aexit__(self, *error: Any) -> None:
        # The owning UOW has already committed/rolled back. Exit in the same
        # task: admitted providers may carry ContextVar tokens issued on entry.
        self.completed = True
        try:
            await self.resources.__aexit__(*error)
        finally:
            # A stored guard may close over its handler context/transaction.
            # Revoke issued capabilities and break that registry-reference cycle
            # on success, failure and cancellation, even if cleanup raises.
            self.guards.clear()
            for identity in self.identities:
                current = _boundaries.get(identity)
                if current is not None and current[1] is self:
                    del _boundaries[identity]
            self.identities.clear()

    async def complete(self) -> None:
        if self.completed:
            raise ConfigurationError("Operation already completed")
        self.completed = True
        for guard in self.guards:
            await self.resources.enter_async_context(guard())


_boundaries: dict[int, tuple[ReferenceType[object], OperationBoundary]] = {}


def bind_handler_boundary(transaction: object, boundary: OperationBoundary) -> None:
    identity = id(transaction)
    boundary.identities.add(identity)

    def discard(reference: ReferenceType[object]) -> None:
        current = _boundaries.get(identity)
        if current is not None and current[0] is reference:
            del _boundaries[identity]

    _boundaries[identity] = (ref(transaction, discard), boundary)


def _boundary(transaction: object) -> OperationBoundary:
    try:
        reference, result = _boundaries[id(transaction)]
        if reference() is not transaction:
            raise KeyError
    except (KeyError, TypeError):
        raise ConfigurationError("Framework-issued operation boundary required") from None
    if result.completed:
        raise ConfigurationError("Operation boundary registration is closed")
    return result


async def retain_handler_resource[T](
    transaction: object, resource: AbstractAsyncContextManager[T]
) -> T:
    """Retain a bounded admission through framework commit/rollback and result release."""
    boundary = _boundary(transaction)
    if boundary.retained >= 128:
        raise ConfigurationError("Operation admission budget exceeded")
    boundary.retained += 1
    return await boundary.resources.enter_async_context(resource)


def defer_handler_completion(
    transaction: object, guard: Callable[[], AbstractAsyncContextManager[None]]
) -> None:
    """Request a final fence; handlers cannot run guards or finish the transaction."""
    boundary = _boundary(transaction)
    if len(boundary.guards) >= 64:
        raise ConfigurationError("Operation completion guard budget exceeded")
    boundary.guards.append(guard)
