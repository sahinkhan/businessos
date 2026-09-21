import asyncio
import os
from uuid import UUID, uuid4

import boto3
import pytest

from businessos.context import RequestContext, TenantContext, bind_request_context
from businessos.providers import (
    BrokerEvent,
    NatsJetStreamPublisher,
    RedisCacheProvider,
    S3ObjectStorageProvider,
)


def _as_tenant(tenant_id: UUID) -> bind_request_context:
    return bind_request_context(RequestContext(tenant=TenantContext(uuid4(), tenant_id, uuid4())))


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_redis_provider_enforces_tenant_key_namespaces() -> None:
    provider = RedisCacheProvider(_required_env("BOS_TEST_REDIS_URL"), namespace="test")
    first_tenant = uuid4()
    second_tenant = uuid4()

    await provider.readiness()
    with pytest.raises(PermissionError):
        await provider.set(first_tenant, "shared", b"unauthorized", 30)
    with _as_tenant(first_tenant):
        await provider.set(first_tenant, "shared", b"first", 30)
        with pytest.raises(PermissionError):
            await provider.get(second_tenant, "shared")
        with pytest.raises(PermissionError):
            await provider.set(second_tenant, "shared", b"overwrite", 30)
        assert await provider.get(first_tenant, "shared") == b"first"
    with _as_tenant(second_tenant):
        await provider.set(second_tenant, "shared", b"second", 30)
        assert await provider.get(second_tenant, "shared") == b"second"
        with pytest.raises(PermissionError):
            await provider.get(first_tenant, "shared")
    with _as_tenant(first_tenant):
        assert await provider.get(first_tenant, "shared") == b"first"
    await provider.close()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_nats_jetstream_provider_publishes_to_managed_stream() -> None:
    token = uuid4().hex
    subject = f"businessos.test.{token}.event"
    provider = NatsJetStreamPublisher(
        (_required_env("BOS_TEST_NATS_URL"),),
        stream_name=f"BUSINESSOS_TEST_{token.upper()}",
        subjects=(f"businessos.test.{token}.>",),
    )

    await provider.start()
    await provider.readiness()
    await provider.publish(subject, b'{"ok":true}', {"event-id": token})
    await provider.close()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_nats_jetstream_provider_restarts_with_existing_identical_stream() -> None:
    token = uuid4().hex
    url = _required_env("BOS_TEST_NATS_URL")
    stream_name = f"BUSINESSOS_RESTART_{token.upper()}"
    subjects = (f"businessos.restart.{token}.>",)
    subject = f"businessos.restart.{token}.event"

    first = NatsJetStreamPublisher((url,), stream_name=stream_name, subjects=subjects)
    await first.start()
    try:
        await first.readiness()
        await first.publish(subject, b"first", {"event-id": str(uuid4())})
    finally:
        await first.close()

    second = NatsJetStreamPublisher((url,), stream_name=stream_name, subjects=subjects)
    await second.start()
    try:
        await second.readiness()
        await second.publish(subject, b"second", {"event-id": str(uuid4())})
    finally:
        await second.close()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_new_durable_replays_published_backlog_and_existing_durable_resumes() -> None:
    token = uuid4().hex
    subject = f"businessos.backlog.{token}.event"
    provider = NatsJetStreamPublisher(
        (_required_env("BOS_TEST_NATS_URL"),),
        stream_name=f"BUSINESSOS_BACKLOG_{token.upper()}",
        subjects=(f"businessos.backlog.{token}.>",),
    )
    seen: list[bytes] = []
    first_received = asyncio.Event()
    second_received = asyncio.Event()

    async def handle(event: BrokerEvent) -> None:
        seen.append(event.payload)
        (first_received if len(seen) == 1 else second_received).set()

    await provider.start()
    try:
        await provider.publish(subject, b"published-before-durable", {"event-id": str(uuid4())})
        subscription = await provider.subscribe(subject, f"BACKLOG_{token}", handle)
        await asyncio.wait_for(first_received.wait(), timeout=10)
        await subscription.close()

        await provider.subscribe(subject, f"BACKLOG_{token}", handle)
        await provider.publish(subject, b"published-after-rebind", {"event-id": str(uuid4())})
        await asyncio.wait_for(second_received.wait(), timeout=10)
        assert seen == [b"published-before-durable", b"published-after-rebind"]
    finally:
        await provider.close()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_existing_new_policy_durable_keeps_its_committed_cursor() -> None:
    from nats.js.api import DeliverPolicy

    token = uuid4().hex
    subject = f"businessos.legacy.{token}.event"
    durable = f"LEGACY_{token}"
    provider = NatsJetStreamPublisher(
        (_required_env("BOS_TEST_NATS_URL"),),
        stream_name=f"BUSINESSOS_LEGACY_{token.upper()}",
        subjects=(f"businessos.legacy.{token}.>",),
    )
    received = asyncio.Event()
    seen: list[bytes] = []

    async def handle(event: BrokerEvent) -> None:
        seen.append(event.payload)
        received.set()

    await provider.start()
    try:
        legacy = await provider._jetstream.subscribe(
            subject,
            durable=durable,
            stream=provider._stream_name,
            manual_ack=True,
            deliver_policy=DeliverPolicy.NEW,
        )
        await provider.publish(subject, b"already-acknowledged", {"event-id": str(uuid4())})
        first = await legacy.next_msg(timeout=10)
        await first.ack()
        await legacy.drain()

        await provider.subscribe(subject, durable, handle)
        await provider.publish(subject, b"after-rebind", {"event-id": str(uuid4())})
        await asyncio.wait_for(received.wait(), timeout=10)
        assert seen == [b"after-rebind"]
    finally:
        await provider.close()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_s3_provider_enforces_tenant_object_prefixes() -> None:
    endpoint = _required_env("BOS_TEST_S3_ENDPOINT")
    access_key = _required_env("BOS_TEST_S3_ACCESS_KEY")
    secret_key = _required_env("BOS_TEST_S3_SECRET_KEY")
    bucket = f"businessos-test-{uuid4().hex}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=bucket)
    provider = S3ObjectStorageProvider(
        bucket=bucket,
        endpoint_url=endpoint,
        region_name="us-east-1",
        access_key=access_key,
        secret_key=secret_key,
    )
    first_tenant = uuid4()
    second_tenant = uuid4()

    await provider.readiness()
    with pytest.raises(PermissionError):
        await provider.put(first_tenant, "shared.txt", b"unauthorized")
    with _as_tenant(first_tenant):
        await provider.put(first_tenant, "shared.txt", b"first")
        with pytest.raises(PermissionError):
            await provider.get(second_tenant, "shared.txt")
        with pytest.raises(PermissionError):
            await provider.put(second_tenant, "shared.txt", b"overwrite")
        assert await provider.get(first_tenant, "shared.txt") == b"first"
    with _as_tenant(second_tenant):
        await provider.put(second_tenant, "shared.txt", b"second")
        assert await provider.get(second_tenant, "shared.txt") == b"second"
        with pytest.raises(PermissionError):
            await provider.get(first_tenant, "shared.txt")
    with _as_tenant(first_tenant):
        assert await provider.get(first_tenant, "shared.txt") == b"first"
    client.delete_object(Bucket=bucket, Key=f"tenant/{first_tenant}/shared.txt")
    client.delete_object(Bucket=bucket, Key=f"tenant/{second_tenant}/shared.txt")
    client.delete_bucket(Bucket=bucket)


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_s3_provider_can_provision_explicit_development_bucket() -> None:
    endpoint = _required_env("BOS_TEST_S3_ENDPOINT")
    access_key = _required_env("BOS_TEST_S3_ACCESS_KEY")
    secret_key = _required_env("BOS_TEST_S3_SECRET_KEY")
    bucket = f"businessos-provision-{uuid4().hex}"
    provider = S3ObjectStorageProvider(
        bucket=bucket,
        endpoint_url=endpoint,
        region_name="us-east-1",
        access_key=access_key,
        secret_key=secret_key,
        provision_bucket=True,
    )

    await provider.start()
    await provider.readiness()

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    client.delete_bucket(Bucket=bucket)
