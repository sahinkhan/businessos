"""Audit the production store with a controlled Redis command-order double.

This models the current generation/expiry-checked SET contract, not a live Redis
server. An earlier request is delayed until a later activity update commits.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from businessos_identity import AuthenticationStrength, PrincipalIdentity, web_sessions
from businessos_identity.web_sessions import ActiveScope, RedisWebSessionStore, WebSession


class ReorderedRedis:
    def __init__(self, session: WebSession) -> None:
        self.raw = session.model_dump_json()
        self.calls = 0
        self.first_waiting = asyncio.Event()
        self.release_first = asyncio.Event()

    async def get(self, _key: str) -> str:
        return self.raw

    async def eval(
        self,
        script: str,
        _key_count: int,
        _key: str,
        expected_generation: int,
        replacement: str,
        _ttl: int,
        observed_at: str,
    ) -> str | None:
        self.calls += 1
        if self.calls == 1:
            self.first_waiting.set()
            await self.release_first.wait()
        current = WebSession.model_validate_json(self.raw)
        candidate = WebSession.model_validate_json(replacement)
        assert "candidate_seen < current_seen" in script
        assert "candidate_idle < idle_expiry" in script
        if current.generation != expected_generation:
            return None
        if (
            candidate.last_seen_at < current.last_seen_at
            or candidate.idle_expires_at < current.idle_expires_at
        ):
            return self.raw
        if not current.live_at(datetime.fromisoformat(observed_at)):
            return None
        self.raw = replacement
        return replacement


@pytest.mark.asyncio
async def test_late_earlier_touch_does_not_undo_newer_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    redis = ReorderedRedis(session)
    store = RedisWebSessionStore(redis)
    monkeypatch.setattr(web_sessions, "_now", lambda: now)
    earlier = asyncio.create_task(store.touch("audit-handle", 1, now + timedelta(minutes=30)))
    await redis.first_waiting.wait()
    later_time = now + timedelta(seconds=10)
    monkeypatch.setattr(web_sessions, "_now", lambda: later_time)
    later = await store.touch("audit-handle", 1, later_time + timedelta(minutes=30))
    redis.release_first.set()
    assert await earlier is not None
    assert later is not None

    final = WebSession.model_validate_json(redis.raw)
    assert final.idle_expires_at >= later.idle_expires_at
    assert final.last_seen_at >= later.last_seen_at
