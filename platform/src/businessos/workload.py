"""Generic worker admission port; Identity supplies the implementation."""

import asyncio
from collections.abc import Generator
from contextlib import AbstractAsyncContextManager, contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Protocol
from uuid import UUID

from businessos.di import DependencyKey
from businessos.messages import HandlerTransaction
from businessos.persistence import TransactionalPersistence


class WorkloadAdmissionDenied(Exception):
    """Invalid worker authority; the delivery itself remains recoverable."""


class VerifiedWorkerProof(Protocol):
    valid_until: datetime


class WorkerWorkloadAdmission(Protocol):
    async def verify(
        self,
        persistence: TransactionalPersistence,
        *,
        installation_id: UUID,
        workload_id: UUID,
        process_class: str,
        purpose: str,
        credential_reference: str,
        credential: bytes,
    ) -> VerifiedWorkerProof: ...

    def operation(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkerProof,
        purpose: str,
    ) -> AbstractAsyncContextManager[None]: ...

    def bind(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkerProof,
        tenant_id: UUID,
        source_event_id: UUID,
        subscriber: str,
        attempt_id: UUID,
        transaction: HandlerTransaction,
    ) -> AbstractAsyncContextManager[object]: ...


WORKER_WORKLOAD_ADMISSION = DependencyKey[WorkerWorkloadAdmission](
    "businessos.identity.workload_execution_authority.v1"
)


_subscriber_permission: ContextVar[tuple[int, UUID, UUID, str] | None] = ContextVar(
    "businessos.worker.subscriber_permission", default=None
)


@contextmanager
def subscriber_permission_admission(
    principal_id: UUID, tenant_id: UUID, permission: str
) -> Generator[None]:
    """Permit only the registered subscriber authorization call in this task."""
    task = asyncio.current_task()
    if task is None:
        raise WorkloadAdmissionDenied("Subscriber permission requires a task")
    token = _subscriber_permission.set((id(task), principal_id, tenant_id, permission))
    try:
        yield
    finally:
        _subscriber_permission.reset(token)


def subscriber_permission_is_admitted(principal_id: UUID, tenant_id: UUID, permission: str) -> bool:
    task = asyncio.current_task()
    return task is not None and _subscriber_permission.get() == (
        id(task),
        principal_id,
        tenant_id,
        permission,
    )
