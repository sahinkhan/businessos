import importlib
import os
import sys
from collections import deque
from typing import Any

import pytest

from businessos.config import get_settings
from businessos.modules import ModuleState


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.providers
@pytest.mark.asyncio
async def test_shipped_asgi_entrypoint_completes_real_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
) -> None:
    monkeypatch.setenv("BOS_ENVIRONMENT", "test")
    monkeypatch.setenv("BOS_DATABASE_URL", postgres_database_url)
    monkeypatch.setenv("BOS_S3_BUCKET", "businessos-development")
    monkeypatch.setenv("BOS_S3_ENDPOINT_URL", os.environ["BOS_TEST_S3_ENDPOINT"])
    monkeypatch.setenv("BOS_S3_REGION_NAME", "us-east-1")
    monkeypatch.setenv("BOS_S3_ACCESS_KEY", os.environ["BOS_TEST_S3_ACCESS_KEY"])
    monkeypatch.setenv("BOS_S3_SECRET_KEY", os.environ["BOS_TEST_S3_SECRET_KEY"])
    monkeypatch.setenv("BOS_S3_PROVISION_BUCKET", "true")
    get_settings.cache_clear()
    sys.modules.pop("businessos.asgi", None)
    asgi = importlib.import_module("businessos.asgi")
    application = asgi.application
    messages: deque[dict[str, Any]] = deque(
        ({"type": "lifespan.startup"}, {"type": "lifespan.shutdown"})
    )
    sent: list[dict[str, Any]] = []
    proof_was_ready = False

    async def receive() -> dict[str, Any]:
        return messages.popleft()

    async def send(message: dict[str, Any]) -> None:
        nonlocal proof_was_ready
        sent.append(message)
        if message["type"] == "lifespan.startup.complete":
            assert application.runtime is not None
            proof = application.runtime.modules.get("example.phase1-proof")
            assert proof.state is ModuleState.ENABLED
            await application.readiness()
            proof_was_ready = True

    try:
        await application(
            {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}},
            receive,
            send,
        )
    finally:
        get_settings.cache_clear()
        sys.modules.pop("businessos.asgi", None)

    assert proof_was_ready
    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
