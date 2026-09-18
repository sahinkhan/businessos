import asyncio
import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import boto3
import pytest
from businessos_identity import (
    ActiveScope,
    AuthenticationStrength,
    AuthorizationTransaction,
    PrincipalIdentity,
    RedisAuthorizationTransactionStore,
    RedisWebSessionStore,
    WebSession,
    web_sessions,
)
from redis.asyncio import Redis, from_url

from businessos.errors import BusinessOSError
from businessos.providers import NatsJetStreamPublisher, RedisCacheProvider, S3ObjectStorageProvider


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


class _DelayedTouchRedis:
    def __init__(self, delegate: Redis) -> None:
        self._delegate = delegate
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    async def eval(self, script: str, *args: object) -> object:
        if "candidate_seen < current_seen" in script:
            self.entered.set()
            await self.release.wait()
        return await cast(Any, self._delegate).eval(script, *args)


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
async def test_redis_web_sessions_rotate_revoke_and_consume_transactions_atomically() -> None:
    namespace = f"test:web-session:{uuid4().hex}"
    factory = cast(Callable[..., Redis], from_url)
    redis = factory(_required_env("BOS_TEST_REDIS_URL"), decode_responses=False)
    sessions = RedisWebSessionStore(redis, namespace=namespace)
    transactions = RedisAuthorizationTransactionStore(redis, namespace=f"{namespace}:oidc")
    now = datetime.now(UTC)
    tenant_id, principal_id = uuid4(), uuid4()
    principal = PrincipalIdentity(
        tenant_id=tenant_id,
        principal_id=principal_id,
        principal_type="user",
        authentication_strength=AuthenticationStrength.MFA,
    )

    def session(generation: int = 1) -> WebSession:
        return WebSession(
            generation=generation,
            principal=principal,
            provider_id="test",
            issued_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=10),
            absolute_expires_at=now + timedelta(hours=1),
            csrf_token=uuid4().hex,
            active_scope=ActiveScope(tenant_id=tenant_id),
        )

    try:
        first = await sessions.create(session())
        second = await sessions.create(session())
        touched = await asyncio.gather(
            *(sessions.touch(first, 1, now + timedelta(minutes=20)) for _ in range(24))
        )
        assert all(item is not None and item.generation == 1 for item in touched)
        rotated = await sessions.rotate(first, session(generation=2))
        assert await sessions.get(first) is None
        assert await sessions.touch(first, 1, now + timedelta(minutes=20)) is None
        rotated_session = await sessions.get(rotated)
        assert rotated_session is not None
        assert rotated_session.generation == 2
        await sessions.revoke_principal(tenant_id, principal_id, "security-event")
        assert await sessions.get(rotated) is None
        assert await sessions.get(second) is None
        assert await sessions.touch(rotated, 2, now + timedelta(minutes=20)) is None

        assert await transactions.allow_login("browser", 1, 60)
        assert not await transactions.allow_login("browser", 1, 60)

        transaction = AuthorizationTransaction(
            state=uuid4().hex,
            nonce=uuid4().hex,
            pkce_verifier=uuid4().hex,
            pkce_challenge=uuid4().hex,
            browser_binding_digest=hashlib.sha256(b"binding").hexdigest(),
            provider_id="test",
            expected_issuer="https://idp.example.test",
            return_to="/",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        await transactions.create(transaction)
        consumed = await transactions.consume(transaction.state, "binding")
        assert consumed.state == transaction.state
        with pytest.raises(BusinessOSError) as replay:
            await transactions.consume(transaction.state, "binding")
        assert replay.value.status_code == 409
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{namespace}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
async def test_redis_session_activity_is_monotonic_and_loses_to_rotation_and_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = f"test:web-session-monotonic:{uuid4().hex}"
    factory = cast(Callable[..., Redis], from_url)
    redis = factory(_required_env("BOS_TEST_REDIS_URL"), decode_responses=False)
    sessions = RedisWebSessionStore(redis, namespace=namespace)
    now = datetime.now(UTC)
    principal = PrincipalIdentity(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="user",
        authentication_strength=AuthenticationStrength.MFA,
    )

    def session(generation: int) -> WebSession:
        return WebSession(
            generation=generation,
            principal=principal,
            provider_id="test",
            issued_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=10),
            absolute_expires_at=now + timedelta(hours=1),
            csrf_token=uuid4().hex,
            active_scope=ActiveScope(tenant_id=principal.tenant_id),
        )

    try:
        handle = await sessions.create(session(1))
        newer_time = now + timedelta(seconds=20)
        monkeypatch.setattr(web_sessions, "_now", lambda: newer_time)
        newer = await sessions.touch(handle, 1, newer_time + timedelta(minutes=20))
        assert newer is not None
        ttl_after_newer = await redis.ttl(sessions._key(handle))

        older_time = now + timedelta(seconds=10)
        monkeypatch.setattr(web_sessions, "_now", lambda: older_time)
        stale = await sessions.touch(handle, 1, older_time + timedelta(minutes=20))
        assert stale is not None
        final = await sessions.get(handle)
        assert final is not None
        assert final.last_seen_at == newer.last_seen_at
        assert final.idle_expires_at == newer.idle_expires_at
        assert await redis.ttl(sessions._key(handle)) >= ttl_after_newer - 2

        delayed_redis = _DelayedTouchRedis(redis)
        delayed_sessions = RedisWebSessionStore(cast(Redis, delayed_redis), namespace=namespace)
        monkeypatch.setattr(web_sessions, "_now", lambda: newer_time + timedelta(seconds=5))
        touching = asyncio.create_task(
            delayed_sessions.touch(handle, 1, newer_time + timedelta(minutes=20))
        )
        await delayed_redis.entered.wait()
        rotated = await sessions.rotate(handle, session(2))
        delayed_redis.release.set()
        assert await touching is None
        assert await sessions.get(handle) is None

        revoke_redis = _DelayedTouchRedis(redis)
        revoke_sessions = RedisWebSessionStore(cast(Redis, revoke_redis), namespace=namespace)
        touching_revoked = asyncio.create_task(
            revoke_sessions.touch(rotated, 2, newer_time + timedelta(minutes=20))
        )
        await revoke_redis.entered.wait()
        await sessions.revoke(rotated, "test-revocation")
        revoke_redis.release.set()
        assert await touching_revoked is None
        assert await sessions.get(rotated) is None
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{namespace}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


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
