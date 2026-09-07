from typing import Any, cast

import pytest

from businessos.providers import NatsJetStreamPublisher


class _Connection:
    is_closed = False
    is_connected = True
    is_reconnecting = False


class _JetStream:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.checked: list[str] = []

    async def stream_info(self, stream_name: str) -> object:
        self.checked.append(stream_name)
        if self.error is not None:
            raise self.error
        return object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connected", "reconnecting", "closed"),
    [(False, False, False), (True, True, False), (False, False, True)],
)
async def test_nats_readiness_rejects_unusable_connection_states(
    connected: bool,
    reconnecting: bool,
    closed: bool,
) -> None:
    provider = NatsJetStreamPublisher(("nats://unused",))
    connection = _Connection()
    cast(Any, connection).is_connected = connected
    cast(Any, connection).is_reconnecting = reconnecting
    cast(Any, connection).is_closed = closed
    provider._connection = connection
    provider._jetstream = _JetStream()

    with pytest.raises(RuntimeError):
        await provider.readiness()


@pytest.mark.asyncio
async def test_nats_readiness_checks_configured_stream() -> None:
    provider = NatsJetStreamPublisher(("nats://unused",))
    jetstream = _JetStream()
    provider._connection = _Connection()
    provider._jetstream = jetstream

    await provider.readiness()

    assert jetstream.checked == ["BUSINESSOS_EVENTS"]


@pytest.mark.asyncio
async def test_nats_readiness_fails_when_stream_is_unavailable() -> None:
    provider = NatsJetStreamPublisher(("nats://unused",))
    provider._connection = _Connection()
    provider._jetstream = _JetStream(RuntimeError("stream unavailable"))

    with pytest.raises(RuntimeError, match="stream unavailable"):
        await provider.readiness()
