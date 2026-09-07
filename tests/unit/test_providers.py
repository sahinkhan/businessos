import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from businessos.providers import (
    BrokerEvent,
    NatsJetStreamPublisher,
    PermanentDeliveryError,
)


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


class _RawSubscription:
    def __init__(self) -> None:
        self.drain_count = 0

    async def drain(self) -> None:
        self.drain_count += 1


class _RawMessage:
    subject = "businessos.events.tenant.example.test.event"
    data = b"{}"

    def __init__(self) -> None:
        self.headers = {"event-id": "event"}
        self.acked = 0
        self.nacked = 0
        self.terminated = 0

    async def ack(self) -> None:
        self.acked += 1

    async def nak(self) -> None:
        self.nacked += 1

    async def term(self) -> None:
        self.terminated += 1


class _SubscribingJetStream(_JetStream):
    def __init__(self) -> None:
        super().__init__()
        self.callback: Callable[[Any], Awaitable[None]] | None = None
        self.subscription = _RawSubscription()

    async def subscribe(self, subject: str, **kwargs: object) -> _RawSubscription:
        self.callback = cast(Callable[[Any], Awaitable[None]], kwargs["cb"])
        return self.subscription


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


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "retry", "permanent", "cancel"])
async def test_nats_delivery_acknowledgement_follows_handler_outcome(outcome: str) -> None:
    provider = NatsJetStreamPublisher(("nats://unused",))
    jetstream = _SubscribingJetStream()
    provider._connection = _Connection()
    provider._jetstream = jetstream

    async def handler(event: BrokerEvent) -> None:
        assert event.payload == b"{}"
        if outcome == "retry":
            raise RuntimeError("retry")
        if outcome == "permanent":
            raise PermanentDeliveryError("reject")
        if outcome == "cancel":
            raise asyncio.CancelledError

    subscription = await provider.subscribe("businessos.events.>", "test", handler)
    message = _RawMessage()
    assert jetstream.callback is not None
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await jetstream.callback(message)
    else:
        await jetstream.callback(message)
    await subscription.close()
    await subscription.close()

    assert message.acked == (1 if outcome == "success" else 0)
    assert message.nacked == (1 if outcome in {"retry", "cancel"} else 0)
    assert message.terminated == (1 if outcome == "permanent" else 0)
    assert jetstream.subscription.drain_count == 1
