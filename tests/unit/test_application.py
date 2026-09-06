from typing import Any, cast

import httpx
import pytest

from businessos.application import ApplicationState
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.http import Request, Response
from businessos.http.middleware import CallNext


def _settings() -> Settings:
    return Settings(environment="test", database_url="postgresql+psycopg://test:test@db/test")


@pytest.mark.asyncio
async def test_diagnostic_endpoints_are_available_through_custom_asgi_app() -> None:
    app = create_application(_settings())
    transport = httpx.ASGITransport(app=cast(Any, app))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        liveness = await client.get("/livez")
        readiness = await client.get("/readyz")
        version = await client.get("/version")

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "live"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready", "checks": []}
    assert version.status_code == 200
    assert "version" in version.json()
    assert liveness.headers["x-correlation-id"]


@pytest.mark.asyncio
async def test_middleware_order_and_lifecycle_are_deterministic() -> None:
    app = create_application(_settings())
    events: list[str] = []

    class RecordingMiddleware:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, request: Request, call_next: CallNext) -> Response:
            events.append(f"{self.name}:before")
            response = await call_next(request)
            events.append(f"{self.name}:after")
            return response

    async def route(request: Request, _: object) -> Response:
        events.append("handler")
        return Response.json({"path": request.path})

    async def startup() -> None:
        events.append("startup")

    async def shutdown() -> None:
        events.append("shutdown")

    app.add_middleware(RecordingMiddleware("first"))
    app.add_middleware(RecordingMiddleware("second"))
    app.router.add_route("GET", "/ordered", route)
    app.on_startup(startup)
    app.on_shutdown(shutdown)

    await app.startup()
    assert app.state is ApplicationState.RUNNING

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ordered")
    await app.shutdown()

    assert response.status_code == 200
    assert events == [
        "startup",
        "first:before",
        "second:before",
        "handler",
        "second:after",
        "first:after",
        "shutdown",
    ]
    assert app.state.value == ApplicationState.STOPPED.value


@pytest.mark.asyncio
async def test_framework_serializes_expected_and_unexpected_errors() -> None:
    app = create_application(_settings())

    async def failure(_: Request, __: object) -> Response:
        raise RuntimeError("secret detail")

    app.router.add_route("GET", "/failure", failure)
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/missing")
        failed = await client.get("/failure")

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert failed.status_code == 500
    assert failed.json() == {"code": "internal_error", "message": "Internal server error"}
