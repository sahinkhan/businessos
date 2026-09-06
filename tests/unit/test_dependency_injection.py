from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from businessos.di import Container, DependencyKey, DependencyScope
from businessos.errors import ConfigurationError


@pytest.mark.asyncio
async def test_request_dependency_is_cached_and_torn_down() -> None:
    key = DependencyKey[str]("request-value")
    lifecycle: list[str] = []

    @asynccontextmanager
    async def resource() -> AsyncGenerator[str]:
        lifecycle.append("enter")
        yield "value"
        lifecycle.append("exit")

    container = Container()
    container.register(key, lambda _: resource(), scope=DependencyScope.REQUEST)

    async with container.request_scope() as scope:
        assert await scope.resolve(key) == "value"
        assert await scope.resolve(key) == "value"
        assert lifecycle == ["enter"]

    assert lifecycle == ["enter", "exit"]


@pytest.mark.asyncio
async def test_scope_must_be_entered() -> None:
    key = DependencyKey[str]("value")
    container = Container()
    container.register(key, lambda _: "value")
    scope = container.request_scope()

    with pytest.raises(ConfigurationError, match="must be entered"):
        await scope.resolve(key)
