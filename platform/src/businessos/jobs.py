"""BusinessOS background-job contracts."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.errors import BusinessOSError
from businessos.registry import OwnedRegistry
from businessos.security import Authorizer
from businessos.telemetry import dispatch_span


class BackoffStrategy(StrEnum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=100)
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay: timedelta = Field(default=timedelta(seconds=1), ge=timedelta(0))
    maximum_delay: timedelta = Field(default=timedelta(minutes=5), ge=timedelta(0))


class JobExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout: timedelta = Field(default=timedelta(minutes=5), gt=timedelta(0))
    cancellable: bool = True
    concurrency_key: str | None = Field(default=None, min_length=1, max_length=200)
    concurrency_limit: int = Field(default=1, ge=1)
    tenant_quota_key: str | None = Field(default=None, min_length=1, max_length=200)


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    tenant_id: UUID
    job_type: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    payload: dict[str, object]
    scheduled_at: datetime | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    correlation_id: str
    trace_id: str | None = None
    policy: JobExecutionPolicy = Field(default_factory=JobExecutionPolicy)


class JobProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    state: JobState
    attempt: int = Field(ge=0)
    completed_units: int | None = Field(default=None, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=500)
    updated_at: datetime


class DeadLetter(BaseModel):
    model_config = ConfigDict(frozen=True)

    job: Job
    attempts: int = Field(ge=1)
    failed_at: datetime
    failure_code: str = Field(min_length=1, max_length=200)
    failure_detail: str | None = Field(default=None, max_length=2000)


class JobQueue(Protocol):
    async def enqueue(self, job: Job) -> None: ...

    async def cancel(self, job_id: UUID, *, tenant_id: UUID) -> bool: ...


class JobProgressStore(Protocol):
    async def record(self, progress: JobProgress) -> None: ...


class DeadLetterStore(Protocol):
    async def put(self, dead_letter: DeadLetter) -> None: ...


JobHandler = Callable[[Job, RequestContext, RequestDependencyScope], Awaitable[None]]


class JobHandlerRegistry(OwnedRegistry[JobHandler]):
    """Owner-scoped job handler contracts; execution is provided by a later adapter."""

    def __init__(
        self,
        gate: ContributionGate | None = None,
        authorizer: Authorizer | None = None,
    ) -> None:
        super().__init__("job handler", gate)
        self._authorizer = authorizer
        self._permissions: dict[tuple[str, ContributionGeneration | None], str | None] = {}

    def add(
        self,
        job_type: str,
        owner: str,
        handler: JobHandler,
        *,
        generation: ContributionGeneration | None = None,
        permission: str | None = None,
    ) -> None:
        self.register(job_type, owner, handler, generation=generation)
        self._permissions[(job_type, generation)] = permission

    async def invoke(
        self,
        job: Job,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> None:
        with dispatch_span("job", job.job_type):
            if context.tenant is None:
                raise BusinessOSError(
                    "unauthenticated",
                    "Authentication required",
                    status_code=401,
                )
            if job.tenant_id != context.tenant.tenant_id:
                raise BusinessOSError(
                    "forbidden",
                    "Job tenant does not match the trusted execution context",
                    status_code=403,
                )
            registered = self.resolve(job.job_type)
            async with self.admit_entry(registered) as handler:
                permission = self._permissions.get((registered.name, registered.generation))
                if permission is not None:
                    if self._authorizer is None:
                        raise RuntimeError("Authorized job dispatch requires an authorizer")
                    await self._authorizer.require(context, permission)
                await handler(job, context, dependencies)

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        removed = {
            (entry.name, entry.generation)
            for entry in self.entries(include_inactive=True)
            if entry.generation == generation
        }
        super().remove_owner_generation(generation)
        for key in removed:
            self._permissions.pop(key, None)
