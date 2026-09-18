"""Independent audit regression: concurrent activity must not invalidate a session.

The double schedules two reads before either atomic compare-and-set. It models
the Redis Lua contract; this is not a live Redis integration test.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from businessos_identity import AuthenticationStrength, PrincipalIdentity
from businessos_identity.web_sessions import ActiveScope, RedisWebSessionStore, WebSession


class ConcurrentTouchRedis:
    def __init__(self, initial: str) -> None:
        self.raw = initial
        self.reads = 0
        self.both_read = asyncio.Event()

    async def get(self, _key: str) -> str:
        snapshot = self.raw
        self.reads += 1
        if self.reads == 2:
            self.both_read.set()
        await self.both_read.wait()
        return snapshot

    async def eval(
        self,
        _script: str,
        _key_count: int,
        _key: str,
        expected_generation: int,
        replacement: str,
        _ttl: int,
        _now: str,
    ) -> int | str:
        current = json.loads(self.raw)
        if current["generation"] != expected_generation:
            return 0
        touched = json.loads(replacement)
        current["last_seen_at"] = touched["last_seen_at"]
        current["idle_expires_at"] = touched["idle_expires_at"]
        self.raw = json.dumps(current)
        return self.raw


@pytest.mark.asyncio
async def test_concurrent_activity_keeps_both_requests_authenticated() -> None:
    now = datetime.now(UTC)
    tenant_id = uuid4()
    session = WebSession(
        principal=PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=uuid4(),
            principal_type="user",
            authentication_strength=AuthenticationStrength.MFA,
        ),
        provider_id="audit-provider",
        issued_at=now - timedelta(minutes=1),
        last_seen_at=now - timedelta(minutes=1),
        idle_expires_at=now + timedelta(minutes=29),
        absolute_expires_at=now + timedelta(hours=8),
        csrf_token="audit-csrf",
        active_scope=ActiveScope(tenant_id=tenant_id),
    )
    redis = ConcurrentTouchRedis(session.model_dump_json())
    store = RedisWebSessionStore(redis)

    results = await asyncio.gather(
        store.touch("audit-handle", session.generation, now + timedelta(minutes=30)),
        store.touch("audit-handle", session.generation, now + timedelta(minutes=30)),
    )

    assert WebSession.model_validate_json(redis.raw).generation == session.generation
    assert all(result is not None for result in results)
