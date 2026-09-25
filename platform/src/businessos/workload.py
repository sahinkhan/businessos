"""Generic worker admission port; Identity supplies the implementation."""

from contextlib import AbstractAsyncContextManager
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
