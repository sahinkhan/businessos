"""Identity-owned installation workload verification and execution authority."""

import asyncio
import hashlib
import hmac
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select, text

from businessos.sdk import HandlerTransaction, TransactionalPersistence

from .contracts import (
    InvalidWorkloadCredential,
    TenantExecutionBinding,
    VerifiedWorkloadIdentity,
    WorkloadIdentityFacts,
    _BindingLease,  # pyright: ignore[reportPrivateUsage]
    _issue_tenant_execution_binding,  # pyright: ignore[reportPrivateUsage]
)
from .models import INSTALLATION_WORKLOADS

_PROOF_LIFETIME = timedelta(seconds=60)


class DatabaseWorkloadExecutionAuthority:
    """Prove possession against an Identity row, then serialize each operation.

    The credential is a high-entropy deployment secret. Only its SHA-256
    verifier is persisted; the raw bytes never enter a row, event, or binding.
    """

    def __init__(self) -> None:
        self._issuer = object()

    async def verify(
        self,
        persistence: TransactionalPersistence,
        *,
        installation_id: UUID,
        workload_id: UUID,
        process_class: str,
        purpose: str,
        credential_reference: str,
        credential: bytes,
    ) -> VerifiedWorkloadIdentity:
        if len(credential) < 32:
            raise InvalidWorkloadCredential("Invalid workload credential")
        result = await persistence.execute(
            select(INSTALLATION_WORKLOADS)
            .where(
                INSTALLATION_WORKLOADS.c.installation_id == installation_id,
                INSTALLATION_WORKLOADS.c.workload_id == workload_id,
            )
            .with_for_update(read=True)
        )
        row = result.mappings().one_or_none()
        if (
            row is None
            or not row["active"]
            or row["revoked_at"] is not None
            or row["process_class"] != process_class
            or purpose not in row["allowed_purposes"]
            or row["credential_reference"] != credential_reference
            or not hmac.compare_digest(
                bytes(row["credential_digest"]), hashlib.sha256(credential).digest()
            )
        ):
            raise InvalidWorkloadCredential("Invalid workload credential")
        now = datetime.now(UTC)
        return VerifiedWorkloadIdentity(
            installation_id=installation_id,
            workload_id=workload_id,
            principal_type="service_account",
            purpose=purpose,
            process_class=process_class,
            credential_reference=credential_reference,
            credential_generation=row["credential_generation"],
            verification_method="sha256-deployment-secret-v1",
            verification_reference=uuid4(),
            valid_from=now,
            valid_until=now + _PROOF_LIFETIME,
            _issuer=self._issuer,
        )

    async def _lock_current(
        self,
        persistence: TransactionalPersistence,
        verified: VerifiedWorkloadIdentity,
        purpose: str,
    ) -> None:
        if (
            not isinstance(cast(object, verified), VerifiedWorkloadIdentity)
            or verified._issuer is not self._issuer  # pyright: ignore[reportPrivateUsage]
            or verified.purpose != purpose
            or not verified.valid_from <= datetime.now(UTC) < verified.valid_until
        ):
            raise InvalidWorkloadCredential("Invalid workload authority")
        result = await persistence.execute(
            text(
                "SELECT platform_identity.admit_workload("
                ":installation_id, :workload_id, :generation, :process_class, :purpose)"
            ),
            {
                "installation_id": verified.installation_id,
                "workload_id": verified.workload_id,
                "generation": verified.credential_generation,
                "process_class": verified.process_class,
                "purpose": purpose,
            },
        )
        if result.scalar_one() is not True:
            raise InvalidWorkloadCredential("Invalid workload authority")

    @asynccontextmanager
    async def operation(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkloadIdentity,
        purpose: str,
    ) -> AsyncGenerator[None]:
        await self._lock_current(persistence, verified, purpose)
        yield

    @asynccontextmanager
    async def bind(
        self,
        persistence: TransactionalPersistence,
        *,
        verified: VerifiedWorkloadIdentity,
        tenant_id: UUID,
        source_event_id: UUID,
        subscriber: str,
        attempt_id: UUID,
        transaction: HandlerTransaction,
    ) -> AsyncGenerator[TenantExecutionBinding]:
        await self._lock_current(persistence, verified, "event-delivery")
        task = asyncio.current_task()
        if task is None or not subscriber:
            raise InvalidWorkloadCredential("Invalid workload execution attempt")
        result = await persistence.execute(
            text("SELECT current_setting('app.tenant_id', true)::uuid = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        if result.scalar_one() is not True:
            raise InvalidWorkloadCredential("Workload tenant does not match transaction")
        lease = _BindingLease()
        binding = TenantExecutionBinding(
            workload=WorkloadIdentityFacts(
                installation_id=verified.installation_id,
                workload_id=verified.workload_id,
                principal_type=verified.principal_type,
                purpose=verified.purpose,
                process_class=verified.process_class,
                credential_reference=verified.credential_reference,
                credential_generation=verified.credential_generation,
                verification_method=verified.verification_method,
                verification_reference=verified.verification_reference,
            ),
            tenant_id=tenant_id,
            source_event_id=source_event_id,
            subscriber=subscriber,
            attempt_id=attempt_id,
            purpose="event-delivery",
            transaction_id=id(transaction),
            valid_from=datetime.now(UTC),
            valid_until=verified.valid_until,
            _task_id=id(task),
            _lease=lease,
        )
        _issue_tenant_execution_binding(binding)
        try:
            yield binding
        finally:
            lease.active = False
