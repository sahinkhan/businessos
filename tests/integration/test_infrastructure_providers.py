import os
from uuid import uuid4

import boto3
import pytest

from businessos.providers import NatsJetStreamPublisher, RedisCacheProvider, S3ObjectStorageProvider


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
    await provider.set(first_tenant, "shared", b"first", 30)
    await provider.set(second_tenant, "shared", b"second", 30)

    assert await provider.get(first_tenant, "shared") == b"first"
    assert await provider.get(second_tenant, "shared") == b"second"
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
    await provider.put(first_tenant, "shared.txt", b"first")
    await provider.put(second_tenant, "shared.txt", b"second")

    assert await provider.get(first_tenant, "shared.txt") == b"first"
    assert await provider.get(second_tenant, "shared.txt") == b"second"
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
