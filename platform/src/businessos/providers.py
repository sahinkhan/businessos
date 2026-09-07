"""Provider capability contracts and replaceable infrastructure adapters."""

# Third-party provider clients expose incomplete type information at their dynamic boundaries.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, cast
from uuid import UUID

from businessos.activation import ContributionGate
from businessos.registry import OwnedRegistry


class HealthProvider(Protocol):
    async def readiness(self) -> None: ...


class EventPublisher(HealthProvider, Protocol):
    async def publish(self, subject: str, payload: bytes, headers: Mapping[str, str]) -> None: ...


class CacheProvider(HealthProvider, Protocol):
    async def get(self, tenant_id: UUID, key: str) -> bytes | None: ...

    async def set(self, tenant_id: UUID, key: str, value: bytes, ttl_seconds: int) -> None: ...


class ObjectStorageProvider(HealthProvider, Protocol):
    async def put(self, tenant_id: UUID, key: str, content: bytes) -> None: ...

    async def get(self, tenant_id: UUID, key: str) -> bytes: ...


class ProviderRegistry(OwnedRegistry[object]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("provider", gate)
        self._started: list[str] = []

    async def start_infrastructure(self) -> None:
        started: list[str] = []
        try:
            for entry in self.entries():
                started.append(entry.name)
                start = getattr(entry.value, "start", None)
                if callable(start):
                    outcome = start()
                    if inspect.isawaitable(outcome):
                        await outcome
                await self._readiness(entry.value)
        except BaseException:
            await self._close_names(reversed(started))
            raise
        self._started.extend(started)

    async def close_infrastructure(self) -> None:
        await self._close_names(reversed(self._started))
        self._started.clear()

    async def readiness(self, capability: str) -> None:
        await self._readiness(self.get(capability))

    async def _close_names(self, names: Iterable[str]) -> None:
        errors: list[BaseException] = []
        for name in names:
            provider = self.get(name)
            close = getattr(provider, "close", None)
            if not callable(close):
                continue
            try:
                outcome = close()
                if inspect.isawaitable(outcome):
                    await outcome
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise BaseExceptionGroup("Infrastructure provider cleanup failed", errors)

    @staticmethod
    async def _readiness(provider: object) -> None:
        readiness = getattr(provider, "readiness", None)
        if not callable(readiness):
            raise RuntimeError("Infrastructure provider does not implement readiness")
        outcome = readiness()
        if not inspect.isawaitable(outcome):
            raise RuntimeError("Infrastructure provider readiness must be asynchronous")
        await outcome


class RedisCacheProvider:
    """Tenant-prefixed Redis adapter loaded only with the providers extra."""

    def __init__(self, url: str, namespace: str = "businessos") -> None:
        from redis.asyncio import Redis, from_url

        factory = cast(Callable[..., Redis], from_url)
        self._client = factory(url, decode_responses=False)
        self._namespace = namespace

    def _key(self, tenant_id: UUID, key: str) -> str:
        return f"{self._namespace}:tenant:{tenant_id}:{key}"

    async def get(self, tenant_id: UUID, key: str) -> bytes | None:
        value = await self._client.get(self._key(tenant_id, key))
        return value if isinstance(value, bytes) else None

    async def set(self, tenant_id: UUID, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._client.set(self._key(tenant_id, key), value, ex=ttl_seconds)

    async def readiness(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()


class NatsJetStreamPublisher:
    """NATS JetStream event publisher loaded only with the providers extra."""

    def __init__(
        self,
        servers: tuple[str, ...],
        *,
        stream_name: str = "BUSINESSOS_EVENTS",
        subjects: tuple[str, ...] = ("businessos.events.>",),
        readiness_timeout_seconds: float = 5.0,
    ) -> None:
        self._servers = servers
        self._stream_name = stream_name
        self._subjects = subjects
        self._readiness_timeout_seconds = readiness_timeout_seconds
        self._connection: Any = None
        self._jetstream: Any = None

    async def start(self) -> None:
        import nats

        connection = await nats.connect(servers=list(self._servers))
        self._connection = connection
        self._jetstream = connection.jetstream()
        await self._jetstream.add_stream(name=self._stream_name, subjects=list(self._subjects))

    async def publish(self, subject: str, payload: bytes, headers: Mapping[str, str]) -> None:
        if self._jetstream is None:
            raise RuntimeError("NATS JetStream provider is not started")
        await self._jetstream.publish(subject, payload, headers=dict(headers))

    async def readiness(self) -> None:
        if self._connection is None or self._jetstream is None:
            raise RuntimeError("NATS JetStream provider is not started")
        if bool(getattr(self._connection, "is_closed", True)):
            raise RuntimeError("NATS connection is closed")
        if not bool(getattr(self._connection, "is_connected", False)):
            raise RuntimeError("NATS connection is disconnected")
        if bool(getattr(self._connection, "is_reconnecting", False)):
            raise RuntimeError("NATS connection is reconnecting")
        async with asyncio.timeout(self._readiness_timeout_seconds):
            await self._jetstream.stream_info(self._stream_name)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.drain()


class S3ObjectStorageProvider:
    """S3-compatible object storage with mandatory tenant key prefixes."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    @staticmethod
    def _key(tenant_id: UUID, key: str) -> str:
        return f"tenant/{tenant_id}/{key.lstrip('/')}"

    async def put(self, tenant_id: UUID, key: str, content: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=self._key(tenant_id, key),
            Body=content,
        )

    async def get(self, tenant_id: UUID, key: str) -> bytes:
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self._bucket,
            Key=self._key(tenant_id, key),
        )
        body = response["Body"]
        return await asyncio.to_thread(body.read)

    async def readiness(self) -> None:
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
