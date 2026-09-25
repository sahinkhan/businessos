"""Installation workload proof is separate from tenant principal identity."""

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_identity import (
    DatabaseWorkloadExecutionAuthority,
    InvalidWorkloadCredential,
)


class _Rows:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    def one_or_none(self) -> dict[str, object] | None:
        return self.row


class _Result:
    def __init__(self, row: dict[str, object] | None, admit: bool) -> None:
        self.row = row
        self.admit = admit

    def mappings(self) -> _Rows:
        return _Rows(self.row)

    def scalar_one(self) -> bool:
        return self.admit


class _Persistence:
    def __init__(
        self, row: dict[str, object] | None, *, admit: bool = True, tenant_matches: bool = True
    ) -> None:
        self.row = row
        self.admit = admit
        self.tenant_matches = tenant_matches
        self.statements: list[str] = []

    async def execute(self, statement: object, _: object = None) -> _Result:
        self.statements.append(str(statement))
        return _Result(
            self.row,
            self.tenant_matches
            if "current_setting('app.tenant_id'" in str(statement)
            else self.admit,
        )


def _row(secret: bytes) -> dict[str, object]:
    return {
        "active": True,
        "revoked_at": None,
        "process_class": "event-worker",
        "allowed_purposes": ["event-delivery", "event-publisher"],
        "credential_reference": "deployment-file-v1",
        "credential_digest": hashlib.sha256(secret).digest(),
        "credential_generation": 1,
    }


async def _verified(
    authority: DatabaseWorkloadExecutionAuthority,
    persistence: _Persistence,
    secret: bytes,
) -> Any:
    return await authority.verify(
        cast(Any, persistence),
        installation_id=uuid4(),
        workload_id=uuid4(),
        process_class="event-worker",
        purpose="event-delivery",
        credential_reference="deployment-file-v1",
        credential=secret,
    )


@pytest.mark.asyncio
async def test_proof_is_non_secret_and_not_tenant_membership() -> None:
    secret = b"a" * 32
    authority = DatabaseWorkloadExecutionAuthority()
    persistence = _Persistence(_row(secret))
    verified = await _verified(authority, persistence, secret)
    assert verified.principal_type == "service_account"
    assert not hasattr(verified, "tenant_id")
    assert secret.decode() not in repr(verified)
    assert all("service_accounts" not in sql for sql in persistence.statements)
    assert any("installation_workloads" in sql for sql in persistence.statements)


@pytest.mark.parametrize("wrong", [b"b" * 32, b"short"])
@pytest.mark.asyncio
async def test_wrong_credential_fails_without_secret_in_exception(wrong: bytes) -> None:
    authority = DatabaseWorkloadExecutionAuthority()
    with pytest.raises(InvalidWorkloadCredential) as raised:
        await _verified(authority, _Persistence(_row(b"a" * 32)), wrong)
    assert wrong.decode() not in str(raised.value)


@pytest.mark.asyncio
async def test_binding_is_one_task_one_transaction_and_expires_on_exit() -> None:
    secret = b"a" * 32
    authority = DatabaseWorkloadExecutionAuthority()
    verified = await _verified(authority, _Persistence(_row(secret)), secret)
    persistence = _Persistence(_row(secret))
    transaction = object()
    tenant, event, attempt = uuid4(), uuid4(), uuid4()
    async with authority.bind(
        cast(Any, persistence),
        verified=verified,
        tenant_id=tenant,
        source_event_id=event,
        subscriber="test.subscriber",
        attempt_id=attempt,
        transaction=cast(Any, transaction),
    ) as binding:
        assert binding.tenant_id == tenant
        assert binding.source_event_id == event
        assert binding.attempt_id == attempt
        assert not hasattr(binding.workload, "_issuer")
        assert secret not in repr(binding).encode()
        binding.assert_active(cast(Any, transaction))
        with pytest.raises(InvalidWorkloadCredential):
            async with authority.bind(
                cast(Any, persistence),
                verified=cast(Any, binding.workload),
                tenant_id=uuid4(),
                source_event_id=uuid4(),
                subscriber="forged.subscriber",
                attempt_id=uuid4(),
                transaction=cast(Any, transaction),
            ):
                pytest.fail("handler facts minted a new binding")
        with pytest.raises(InvalidWorkloadCredential):
            binding.assert_active(cast(Any, object()))

        async def another_task() -> None:
            with pytest.raises(InvalidWorkloadCredential):
                binding.assert_active(cast(Any, transaction))

        await asyncio.create_task(another_task())
    with pytest.raises(InvalidWorkloadCredential):
        binding.assert_active(cast(Any, transaction))


@pytest.mark.asyncio
async def test_changed_generation_denies_next_operation() -> None:
    secret = b"a" * 32
    authority = DatabaseWorkloadExecutionAuthority()
    verified = await _verified(authority, _Persistence(_row(secret)), secret)
    with pytest.raises(InvalidWorkloadCredential):
        async with authority.operation(
            cast(Any, _Persistence(_row(secret), admit=False)),
            verified=verified,
            purpose="event-delivery",
        ):
            pytest.fail("stale generation was admitted")


@pytest.mark.asyncio
async def test_binding_denies_tenant_that_differs_from_transaction() -> None:
    secret = b"a" * 32
    authority = DatabaseWorkloadExecutionAuthority()
    verified = await _verified(authority, _Persistence(_row(secret)), secret)
    with pytest.raises(InvalidWorkloadCredential, match="tenant"):
        async with authority.bind(
            cast(Any, _Persistence(_row(secret), tenant_matches=False)),
            verified=verified,
            tenant_id=uuid4(),
            source_event_id=uuid4(),
            subscriber="test.subscriber",
            attempt_id=uuid4(),
            transaction=cast(Any, object()),
        ):
            pytest.fail("mismatched tenant was admitted")


@pytest.mark.asyncio
async def test_expired_proof_fails_before_admission() -> None:
    secret = b"a" * 32
    authority = DatabaseWorkloadExecutionAuthority()
    verified = await _verified(authority, _Persistence(_row(secret)), secret)
    object.__setattr__(verified, "valid_until", datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(InvalidWorkloadCredential):
        async with authority.operation(
            cast(Any, _Persistence(_row(secret))),
            verified=verified,
            purpose="event-delivery",
        ):
            pytest.fail("expired proof was admitted")
