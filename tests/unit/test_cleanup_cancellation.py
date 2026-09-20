import asyncio
from typing import Any, cast

import anyio
import pytest

from businessos.application import ApplicationState, BusinessOSApplication
from businessos.config import Settings
from businessos.di import Container
from businessos.http import Router
from businessos.persistence.uow import SQLAlchemyUnitOfWork


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
    )


@pytest.mark.asyncio
async def test_application_shutdown_preserves_anyio_cancel_scope_identity() -> None:
    app = BusinessOSApplication(_settings(), router=Router(), container=Container())
    cleanup_completed = asyncio.Event()

    async def start() -> None:
        return None

    async def stop() -> None:
        await asyncio.sleep(0.02)
        cleanup_completed.set()

    app.add_lifecycle("probe", start, stop)
    await app.startup()

    with anyio.CancelScope() as cancel_scope:
        asyncio.get_running_loop().call_later(0.001, cancel_scope.cancel)
        await app.shutdown()

    assert cancel_scope.cancelled_caught
    assert cleanup_completed.is_set()
    assert app.state is ApplicationState.STOPPED


@pytest.mark.asyncio
async def test_unit_of_work_cleanup_preserves_anyio_cancel_scope_identity() -> None:
    cleanup_steps: list[str] = []

    class Session:
        async def begin(self) -> None:
            return None

        async def rollback(self) -> None:
            await asyncio.sleep(0.01)
            cleanup_steps.append("rollback")

        async def close(self) -> None:
            await asyncio.sleep(0.01)
            cleanup_steps.append("close")

    session = Session()
    unit_of_work = SQLAlchemyUnitOfWork(cast(Any, lambda: session), None)

    with anyio.CancelScope() as cancel_scope:
        async with unit_of_work:
            asyncio.get_running_loop().call_later(0.001, cancel_scope.cancel)

    assert cancel_scope.cancelled_caught
    assert cleanup_steps == ["rollback", "close"]
    assert unit_of_work.session is None
