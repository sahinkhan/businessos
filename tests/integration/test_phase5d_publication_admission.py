"""Real private-pool congestion and repeated lease-finalizer cancellation."""

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from businessos_metadata.ui_contracts import UIOverlayScope
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import QueuePool

from businessos.errors import ConfigurationError, ProtectedDatabaseCapacityError
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.publication_database import _PublicationPool
from tests.integration.test_phase5d_private_publication import _state
from tests.integration.test_phase5d_ui import Harness, create, publish
from tests.integration.test_phase5d_ui import ui_harness as ui_harness

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


def _authority(h: Harness) -> Any:
    assert h.app.runtime is not None
    executor = h.app.runtime.messages._publication
    assert executor is not None
    return executor.authority


async def test_real_exhausted_private_pool_bounds_all_concurrent_publication_admissions(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    authority = _authority(h)
    pool = authority._active
    assert isinstance(pool, _PublicationPool)
    authority._pool_timeout = 0.25
    contexts = []
    rows = []
    assert h.context.tenant is not None
    for _ in range(8):
        context = replace(h.context, tenant=replace(h.context.tenant, tenant_id=uuid4()))
        contexts.append(context)
        rows.append(await create(h, context=context))
    before = _state(h)
    validations = 0
    all_entered = asyncio.Event()
    original_validate = _PublicationPool.validate

    async def validate(selected: _PublicationPool) -> None:
        nonlocal validations
        if selected is pool:
            validations += 1
            if validations == 8:
                all_entered.set()
        await original_validate(selected)

    monkeypatch.setattr(_PublicationPool, "validate", validate)

    async def call(index: int) -> float:
        started = asyncio.get_running_loop().time()
        with pytest.raises(ProtectedDatabaseCapacityError):
            await publish(h, rows[index], contexts[index])
        return asyncio.get_running_loop().time() - started

    async with AsyncExitStack() as stack:
        for _ in range(authority._pool_size):
            await stack.enter_async_context(pool.engine.connect())
        tasks = [asyncio.create_task(call(index)) for index in range(8)]
        try:
            await asyncio.wait_for(all_entered.wait(), 0.65)
            queue = pool.engine.pool
            assert isinstance(queue, QueuePool)
            assert queue.checkedout() == authority._pool_size
            # Resolution uses ordinary Metadata, independent from issuer exhaustion.
            assert (await asyncio.wait_for(h.resolve(), 3)).resolved is not None
            durations = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    print("PRIVATE_ADMISSION_TIMINGS:" + json.dumps(durations))
    assert max(durations) < 0.65, "Eight callers must not queue for eight pool timeouts"
    assert validations == 8
    assert authority._active is pool
    assert authority._leases == {}
    assert _state(h) == before
    authority._pool_timeout = 10
    assert (await publish(h, rows[0], contexts[0])).active_revision_id is not None


@pytest.mark.parametrize("shutdown", [False, True])
async def test_real_congested_admission_cancel_rotation_and_shutdown(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    shutdown: bool,
) -> None:
    h = ui_harness
    rows = [await create(h, kind=kind) for kind in (UIOverlayScope.TENANT, UIOverlayScope.COMPANY)]
    authority = _authority(h)
    old = authority._active
    assert isinstance(old, _PublicationPool)
    validations = 0
    all_entered = asyncio.Event()
    original_validate = _PublicationPool.validate
    original_close = _PublicationPool.close
    disposals = 0

    async def validate(pool: _PublicationPool) -> None:
        nonlocal validations
        if pool is old:
            validations += 1
            if validations == 2:
                all_entered.set()
        await original_validate(pool)

    async def close(pool: _PublicationPool) -> None:
        nonlocal disposals
        if pool is old:
            disposals += 1
        await original_close(pool)

    monkeypatch.setattr(_PublicationPool, "validate", validate)
    monkeypatch.setattr(_PublicationPool, "close", close)
    async with AsyncExitStack() as stack:
        for _ in range(authority._pool_size):
            await stack.enter_async_context(old.engine.connect())
        tasks = [asyncio.create_task(publish(h, row)) for row in rows]
        try:
            await asyncio.wait_for(all_entered.wait(), 3)
            assert authority._leases[old] == 2
            await asyncio.wait_for(authority.rotate(h.database.ui_publication_url), 3)
            assert authority._active is not old
            assert disposals == 0, "Rotation must retain pending validation leases"
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(tasks[0], 3)
            assert authority._leases[old] == 1
            if shutdown:
                await asyncio.wait_for(authority.close(), 3)
            await stack.aclose()
            with pytest.raises(ConfigurationError, match="changed during admission"):
                await asyncio.wait_for(tasks[1], 3)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert authority._leases == {}
    assert disposals == 1
    assert (await h.resolve()).resolved is not None
    if shutdown:
        with pytest.raises(ConfigurationError, match="profile unavailable"):
            await publish(h, rows[0])
        await authority.close()
        assert disposals == 1
    else:
        assert (await publish(h, rows[0])).active_revision_id is not None


async def test_real_repeated_cancellation_at_contended_finalizer_is_exactly_once(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    authority = _authority(h)
    original_commit = SQLAlchemyUnitOfWork.commit
    original_close = AsyncSession.close
    original_dispose = _PublicationPool.close
    original_release = authority._release

    async def cycle(kind: UIOverlayScope) -> None:
        row = await create(h, kind=kind)
        before = _state(h)
        old = authority._active
        assert isinstance(old, _PublicationPool)
        entered, session_closed, finalizer_entered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        sessions: list[AsyncSession] = []
        disposal_count = 0

        async def commit(unit: SQLAlchemyUnitOfWork) -> None:
            assert unit.session is not None
            sessions.append(unit.session)
            entered.set()
            await asyncio.Event().wait()

        async def close(session: AsyncSession) -> None:
            await original_close(session)
            if session in sessions:
                session_closed.set()

        async def dispose(pool: _PublicationPool) -> None:
            nonlocal disposal_count
            if pool is old:
                disposal_count += 1
                assert session_closed.is_set(), "Lease release must follow SQL cleanup"
            await original_dispose(pool)

        async def release(lease: Any, *, revoke: bool) -> None:
            finalizer_entered.set()
            await original_release(lease, revoke=revoke)

        monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", commit)
        monkeypatch.setattr(AsyncSession, "close", close)
        monkeypatch.setattr(_PublicationPool, "close", dispose)
        monkeypatch.setattr(authority, "_release", release)
        task = asyncio.create_task(publish(h, row))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.wait_for(authority.rotate(h.database.ui_publication_url), 3)
            assert authority._leases[old] == 1 and disposal_count == 0
            async with authority._lock:
                task.cancel()
                await asyncio.wait_for(session_closed.wait(), 3)
                await asyncio.wait_for(finalizer_entered.wait(), 3)
                for _ in range(3):
                    task.cancel()
                    await asyncio.sleep(0)
                    assert not task.done(), "Cancellation must not abandon the lease finalizer"
                assert authority._leases[old] == 1
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", original_commit)
            monkeypatch.setattr(authority, "_release", original_release)
        assert sessions and all(not session.in_transaction() for session in sessions)
        assert authority._leases == {}
        assert disposal_count == 1
        assert _state(h) == before
        assert (await asyncio.wait_for(publish(h, row), 5)).active_revision_id is not None
        assert disposal_count == 1

    for kind in (UIOverlayScope.TENANT, UIOverlayScope.COMPANY, UIOverlayScope.SITE):
        await cycle(kind)
    await authority.close()
    await authority.close()
    assert authority._leases == {}
