"""Real Redis proof for the bounded Phase 4.5 browser session adapter."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_identity.contracts import PrincipalIdentity
from businessos_identity.web_sessions import (
    ActiveScope,
    AuthorizationTransaction,
    RedisAuthorizationTransactionStore,
    RedisWebSessionStore,
    WebSession,
)
from redis.asyncio import from_url

from businessos.sdk import BusinessOSError


@pytest.mark.asyncio
async def test_redis_session_rotation_and_transaction_replay() -> None:
    url = os.getenv("BOS_TEST_REDIS_URL")
    if url is None:
        pytest.skip("BOS_TEST_REDIS_URL is not configured")
    redis = cast(Any, from_url)(url, decode_responses=False)
    namespace = f"businessos:phase45-test:{uuid4().hex}"
    sessions = RedisWebSessionStore(redis, namespace)
    transactions = RedisAuthorizationTransactionStore(redis, namespace)
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = WebSession(
        principal=PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=uuid4(),
            principal_type="user",
            authentication_strength="oidc",
        ),
        provider_id="default",
        issued_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=5),
        absolute_expires_at=now + timedelta(hours=1),
        csrf_token="csrf-before",
        active_scope=ActiveScope(tenant_id=tenant_id),
    )
    try:
        handle = await sessions.create(session)
        assert (await sessions.get(handle)) == session
        replacement = session.model_copy(update={"generation": 2, "csrf_token": "csrf-after"})
        rotated = await sessions.rotate(handle, replacement)
        assert await sessions.get(handle) is None
        assert (await sessions.get(rotated)) == replacement
        assert await sessions.touch(rotated, 1, now + timedelta(minutes=10)) is None
        assert await sessions.get(rotated) == replacement

        transaction = AuthorizationTransaction(
            state="state",
            nonce="nonce",
            pkce_verifier="verifier",
            pkce_challenge="challenge",
            browser_binding_digest=hashlib.sha256(b"binding").hexdigest(),
            provider_id="default",
            expected_issuer="https://idp.example",
            return_to="/",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        await transactions.create(transaction)
        assert await transactions.consume("state", "binding") == transaction
        with pytest.raises(BusinessOSError):
            await transactions.consume("state", "binding")
        await sessions.revoke(rotated, "logout")
        assert await sessions.get(rotated) is None
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{namespace}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
