import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from businessos.activation import ContributionGate
from businessos.context import RequestContext, TenantContext
from businessos.di import Container
from businessos.errors import BusinessOSError
from businessos.jobs import BackoffStrategy, DeadLetter, Job, JobHandlerRegistry, JobState
from businessos.security import Authorizer


class DenyPolicy:
    async def is_allowed(
        self,
        principal_id: object,
        tenant: TenantContext,
        permission: str,
    ) -> bool:
        return False


def test_job_defaults_define_retry_and_dead_letter_conventions() -> None:
    job = Job(
        job_id=uuid4(),
        tenant_id=uuid4(),
        job_type="proof.rebuild",
        payload={"scope": "all"},
        correlation_id="correlation-1",
        trace_id="trace-1",
    )

    assert job.policy.retry.max_attempts == 3
    assert job.policy.retry.strategy is BackoffStrategy.EXPONENTIAL
    assert job.policy.cancellable
    assert job.policy.concurrency_limit == 1

    dead_letter = DeadLetter(
        job=job,
        attempts=job.policy.retry.max_attempts,
        failed_at=datetime.now(UTC),
        failure_code="attempts_exhausted",
    )
    assert dead_letter.job.job_id == job.job_id
    assert JobState.DEAD_LETTERED.value == "dead_lettered"


@pytest.mark.asyncio
async def test_job_dispatch_enforces_permission_before_handler() -> None:
    registry = JobHandlerRegistry(authorizer=Authorizer(DenyPolicy()))
    called = False

    async def handler(job: Job, context: RequestContext, dependencies: object) -> None:
        nonlocal called
        called = True

    registry.add(
        "proof.rebuild",
        "example",
        handler,
        permission="example.proof.rebuild",
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    context = RequestContext(tenant=tenant)
    job = Job(
        job_id=uuid4(),
        tenant_id=tenant.tenant_id,
        job_type="proof.rebuild",
        payload={},
        correlation_id=context.correlation_id,
    )
    container = Container()
    async with container.request_scope() as dependencies:
        with pytest.raises(BusinessOSError) as raised:
            await registry.invoke(job, context, dependencies)

    assert raised.value.code == "forbidden"
    assert not called


@pytest.mark.asyncio
async def test_job_authorization_and_handler_hold_one_generation() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    invoked: list[str] = []

    class BlockingPolicy:
        async def is_allowed(
            self,
            principal_id: object,
            tenant: TenantContext,
            permission: str,
        ) -> bool:
            entered.set()
            await release.wait()
            return permission == "old.permission"

    gate = ContributionGate()
    generation = gate.reserve("example")
    registry = JobHandlerRegistry(gate, Authorizer(BlockingPolicy()))

    async def handler(job: Job, context: RequestContext, dependencies: object) -> None:
        invoked.append("old")

    registry.add(
        "proof.rebuild",
        "example",
        handler,
        generation=generation,
        permission="old.permission",
    )
    gate.publish(generation)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    job = Job(
        job_id=uuid4(),
        tenant_id=tenant.tenant_id,
        job_type="proof.rebuild",
        payload={},
        correlation_id="job-race",
    )
    container = Container()
    async with container.request_scope() as dependencies:
        task = asyncio.create_task(
            registry.invoke(job, RequestContext(tenant=tenant), dependencies)
        )
        await entered.wait()
        drain = asyncio.create_task(gate.close_and_drain(generation, timeout_seconds=1))
        await asyncio.sleep(0)
        assert not drain.done()
        release.set()
        await task
        await drain

    assert invoked == ["old"]
