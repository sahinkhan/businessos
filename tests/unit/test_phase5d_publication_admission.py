"""Private publication deadlines and owned lease finalizers."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_metadata.module import PublishUIOverlay

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import TenantContext
from businessos.errors import ConfigurationError, NotFoundError, ProtectedDatabaseCapacityError
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.publication_database import PublicationDatabaseAuthority, _PublicationPool

pytestmark = pytest.mark.asyncio


class _Pool(_PublicationPool):
    def __init__(self, url: str, *, size: int, timeout: float, database_name: str) -> None:
        self.database_name = database_name
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_release.set()
        self.validations = 0
        self.disposals = 0
        self.sessions = cast(Any, lambda: None)

    async def validate(self) -> None:
        self.validations += 1
        self.entered.set()
        await self.release.wait()

    async def close(self) -> None:
        self.disposals += 1
        self.close_entered.set()
        await self.close_release.wait()


class _Authority(PublicationDatabaseAuthority):
    _pool_type = _Pool


@dataclass(frozen=True)
class _Registered:
    owner: str
    generation: ContributionGeneration
    direct_dependencies: object


def _authority(timeout: float = 0.1) -> tuple[_Authority, _Pool, _Registered, TenantContext]:
    gate = ContributionGate()
    generation = gate.reserve("foundation.metadata")
    gate.publish(generation)
    authority = _Authority(
        governance_url="postgresql+psycopg://businessos_ui_publication:local@db/example",
        database_name="example",
        pool_size=1,
        pool_timeout=timeout,
        gate=gate,
    )
    registration = _Registered("foundation.metadata", generation, ())
    authority._registrations[id(registration)] = cast(
        Any,
        SimpleNamespace(
            registered=registration, command_type=PublishUIOverlay, generation=generation
        ),
    )
    assert isinstance(authority._active, _Pool)
    return (
        authority,
        authority._active,
        registration,
        TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4()),
    )


async def test_private_publication_validation_queue_has_one_total_deadline() -> None:
    authority, pool, registered, tenant = _authority()
    pool.release.clear()
    started = asyncio.get_running_loop().time()

    async def call() -> float:
        begin = asyncio.get_running_loop().time()
        with pytest.raises(ProtectedDatabaseCapacityError):
            async with authority.for_command(registered, PublishUIOverlay, tenant):
                pytest.fail("Blocked validation admitted a publication")
        return asyncio.get_running_loop().time() - begin

    durations = await asyncio.wait_for(asyncio.gather(*(call() for _ in range(8))), 0.5)
    assert pool.validations == 8, "Validation must run outside the authority mutex"
    assert max(durations) < 0.3
    assert asyncio.get_running_loop().time() - started < 0.3
    assert authority._active is pool
    assert authority._leases == {}
    await authority.close()
    assert pool.disposals == 1


async def test_private_publication_mutex_wait_is_inside_admission_deadline() -> None:
    authority, pool, registered, tenant = _authority()
    async with authority._lock:
        with pytest.raises(ProtectedDatabaseCapacityError):
            async with authority.for_command(registered, PublishUIOverlay, tenant):
                pytest.fail("Contended state mutex admitted a publication")
    assert pool.validations == 0
    assert authority._leases == {}
    await authority.close()


@pytest.mark.parametrize("change", ["rotation", "shutdown", "generation"])
async def test_private_admission_rechecks_pool_and_generation_after_validation(change: str) -> None:
    authority, pool, registered, tenant = _authority(1)
    pool.release.clear()

    async def call() -> None:
        async with authority.for_command(registered, PublishUIOverlay, tenant):
            pytest.fail("Changed authority admitted a stale publication")

    task = asyncio.create_task(call())
    await asyncio.wait_for(pool.entered.wait(), 1)
    assert authority._leases[pool] == 1
    async with authority._lock:
        pass
    if change == "rotation":
        await authority.rotate("postgresql+psycopg://businessos_ui_publication:new@db/example")
    elif change == "shutdown":
        await authority.close()
    else:
        authority._gate.discard(registered.generation)
    assert pool.disposals == 0, "An admission reservation must retain its selected pool"
    pool.release.set()
    with pytest.raises((ConfigurationError, NotFoundError)):
        await asyncio.wait_for(task, 1)
    assert authority._leases == {}
    await authority.close()
    assert pool.disposals == 1


async def test_private_uow_checkout_uses_remaining_admission_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, pool, registered, tenant = _authority()
    pool.release.clear()
    checkout = asyncio.Event()

    async def enter(unit: SQLAlchemyUnitOfWork) -> SQLAlchemyUnitOfWork:
        checkout.set()
        await asyncio.Event().wait()
        return unit

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "__aenter__", enter)
    loop = asyncio.get_running_loop()
    release = loop.call_later(0.06, pool.release.set)
    started = loop.time()
    try:
        with pytest.raises(ProtectedDatabaseCapacityError):
            async with authority.for_command(registered, PublishUIOverlay, tenant) as unit:
                async with unit:
                    pytest.fail("Unavailable checkout admitted a transaction")
    finally:
        release.cancel()
    assert checkout.is_set()
    assert loop.time() - started < 0.15, "Checkout must not receive another full timeout"
    assert authority._leases == {}
    await authority.close()


@pytest.mark.parametrize("repeat", range(3))
async def test_private_finalizer_survives_repeated_cancel_and_disposes_once(
    repeat: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, pool, registered, tenant = _authority(1)
    entered, finalizer_entered = asyncio.Event(), asyncio.Event()
    original_release = authority._release

    async def release(lease: Any, *, revoke: bool) -> None:
        finalizer_entered.set()
        await original_release(lease, revoke=revoke)
        # The owned token is idempotent even if a finalizer is invoked twice.
        await original_release(lease, revoke=revoke)

    monkeypatch.setattr(authority, "_release", release)

    async def call() -> None:
        async with authority.for_command(registered, PublishUIOverlay, tenant):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(call())
    await asyncio.wait_for(entered.wait(), 1)
    await authority.rotate("postgresql+psycopg://businessos_ui_publication:new@db/example")
    assert pool.disposals == 0
    pool.close_release.clear()
    async with authority._lock:
        task.cancel()
        await asyncio.wait_for(finalizer_entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert authority._leases[pool] == 1
    await asyncio.wait_for(pool.close_entered.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done(), "Disposal must also remain owned"
    pool.close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert authority._leases == {}
    assert pool.disposals == 1
    async with authority.for_command(registered, PublishUIOverlay, tenant):
        pass
    await authority.close()
    await authority.close()
    assert pool.disposals == 1


async def test_private_validation_cancellation_during_shutdown_releases_reservation() -> None:
    authority, pool, registered, tenant = _authority(1)
    pool.release.clear()

    async def call() -> AsyncGenerator[None]:
        async with authority.for_command(registered, PublishUIOverlay, tenant):
            yield

    async def execute() -> None:
        async for _ in call():
            pytest.fail("Validation remains blocked")

    task = asyncio.create_task(execute())
    await asyncio.wait_for(pool.entered.wait(), 1)
    await authority.close()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert authority._leases == {}
    assert pool.disposals == 1


async def test_repeated_cancel_during_failed_rotation_still_revokes_old_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, old, registered, tenant = _authority(1)
    replacement_entered = asyncio.Event()
    replacement: _Pool | None = None
    original_validate = _Pool.validate

    async def validate(pool: _Pool) -> None:
        nonlocal replacement
        if pool is old:
            await original_validate(pool)
            return
        replacement = pool
        pool.close_release.clear()
        replacement_entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(_Pool, "validate", validate)
    task = asyncio.create_task(
        authority.rotate("postgresql+psycopg://businessos_ui_publication:new@db/example")
    )
    await asyncio.wait_for(replacement_entered.wait(), 1)
    task.cancel()
    assert replacement is not None
    await asyncio.wait_for(replacement.close_entered.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    replacement.close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert authority._active is None
    assert old.disposals == replacement.disposals == 1
    with pytest.raises(ConfigurationError, match="profile unavailable"):
        async with authority.for_command(registered, PublishUIOverlay, tenant):
            pytest.fail("Cancelled rotation left authority active")
    await authority.close()
