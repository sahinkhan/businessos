"""Committed-source comparisons reject broker-controlled changes."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from businessos.event_source import CommittedOutboxSourceVerifier, strict_event_payload
from businessos.providers import PermanentDeliveryError


class _Result:
    def __init__(self, source: object | None) -> None:
        self.source = source

    def scalar_one_or_none(self) -> object | None:
        return self.source


class _Persistence:
    def __init__(self, source: object | None) -> None:
        self.source = source

    async def execute(self, _: object) -> _Result:
        return _Result(self.source)


class _Uow:
    def __init__(self, source: object | None) -> None:
        self.persistence = _Persistence(source)

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Factory:
    def __init__(self, source: object | None) -> None:
        self.source = source

    def system(self) -> _Uow:
        return _Uow(self.source)


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type="test.provenance.v1",
        schema_version=1,
        occurred_at=datetime.now(UTC),
        correlation_id="correlation",
        causation_id="cause",
        payload={"nested": {"value": 1}, "origin": "verified"},
    )


def _claims(source: SimpleNamespace) -> dict[str, Any]:
    return {
        "event_id": source.id,
        "tenant_id": source.tenant_id,
        "event_type": source.event_type,
        "schema_version": source.schema_version,
        "occurred_at": source.occurred_at,
        "correlation_id": source.correlation_id,
        "causation_id": source.causation_id,
        "payload": source.payload,
    }


@pytest.mark.asyncio
async def test_exact_committed_source_is_accepted() -> None:
    source = _source()
    verifier = CommittedOutboxSourceVerifier(cast(Any, _Factory(source)))
    await verifier.verify(**_claims(source))


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("event_id", uuid4()),
        ("tenant_id", uuid4()),
        ("event_type", "changed"),
        ("schema_version", 2),
        ("occurred_at", datetime(2020, 1, 1, tzinfo=UTC)),
        ("correlation_id", "changed"),
        ("causation_id", "changed"),
        ("payload", {"nested": {"value": 2}, "origin": "verified"}),
    ],
)
@pytest.mark.asyncio
async def test_any_source_change_denies_before_handler(field: str, replacement: object) -> None:
    source = _source()
    claims = _claims(source)
    claims[field] = replacement
    verifier = CommittedOutboxSourceVerifier(cast(Any, _Factory(source)))
    with pytest.raises(PermanentDeliveryError, match="committed source"):
        await verifier.verify(**claims)


@pytest.mark.asyncio
async def test_unknown_source_denies() -> None:
    source = _source()
    verifier = CommittedOutboxSourceVerifier(cast(Any, _Factory(None)))
    with pytest.raises(PermanentDeliveryError, match="committed source"):
        await verifier.verify(**_claims(source))


@pytest.mark.parametrize(
    "payload",
    [
        b'{"event_id":"a","event_id":"b"}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"\xff",
        b'{"value":"\\ud800"}',
    ],
)
def test_ambiguous_json_denies(payload: bytes) -> None:
    with pytest.raises(PermanentDeliveryError):
        strict_event_payload(payload)


def test_equivalent_key_order_is_canonical() -> None:
    source = strict_event_payload(json.dumps({"b": 1, "a": {"y": 2, "x": 3}}).encode())
    delivered = strict_event_payload(b'{"a":{"x":3,"y":2},"b":1}')
    assert source == delivered
