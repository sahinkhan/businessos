"""Completion is framework-owned, identity-bound, and retains same-task contexts."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import copy
from gc import collect
from typing import cast
from uuid import UUID, uuid4
from weakref import ref

import pytest

from businessos.messages import handler_transaction_view
from businessos.operation_boundary import OperationBoundary
from businessos.sdk import (
    BusinessOSError,
    ConfigurationError,
    RequestContext,
    TenantContext,
    TransactionalPersistence,
    defer_handler_completion,
    retain_handler_resource,
)
from businessos.security import Authorizer
from tests.unit.test_messages import FakeUnitOfWork


@pytest.mark.asyncio
async def test_admission_and_final_guard_span_evidence_commit_and_cleanup() -> None:
    timeline: list[str] = []
    active: ContextVar[bool] = ContextVar("operation-boundary-test", default=False)

    @asynccontextmanager
    async def resource() -> AsyncIterator[None]:
        token = active.set(True)
        timeline.append("admit")
        try:
            yield
        finally:
            assert active.get()
            active.reset(token)
            timeline.append("release")

    @asynccontextmanager
    async def final_guard() -> AsyncIterator[None]:
        timeline.append("fence")
        try:
            yield
        finally:
            timeline.append("unfence")

    async with OperationBoundary() as boundary:
        async with FakeUnitOfWork(timeline) as uow:
            transaction = handler_transaction_view(uow, boundary)
            await retain_handler_resource(transaction, resource())
            defer_handler_completion(transaction, final_guard)
            with pytest.raises(ConfigurationError):
                defer_handler_completion(copy(transaction), final_guard)
            timeline.append("evidence")
            await boundary.complete()
            with pytest.raises(ConfigurationError):
                defer_handler_completion(transaction, final_guard)
            await uow.commit()
    assert timeline == [
        "begin",
        "admit",
        "evidence",
        "fence",
        "commit",
        "close",
        "unfence",
        "release",
    ]
    assert not active.get()


@pytest.mark.asyncio
async def test_unissued_transaction_cannot_retain_or_register_completion() -> None:
    transaction = handler_transaction_view(FakeUnitOfWork([]))

    @asynccontextmanager
    async def guard() -> AsyncIterator[None]:
        yield

    with pytest.raises(ConfigurationError):
        defer_handler_completion(transaction, guard)


@pytest.mark.asyncio
async def test_completed_operation_does_not_retain_handler_context() -> None:
    async def finish() -> object:
        async with OperationBoundary() as boundary:
            async with FakeUnitOfWork([]) as uow:
                transaction = handler_transaction_view(uow, boundary)

                @asynccontextmanager
                async def guard() -> AsyncIterator[None]:
                    assert transaction.persistence is not None
                    yield

                defer_handler_completion(transaction, guard)
                reference = ref(transaction)
                await boundary.complete()
                await uow.commit()
        return reference

    reference = await finish()
    collect()
    assert callable(reference)
    assert reference() is None


@pytest.mark.asyncio
async def test_failed_operation_revokes_late_completion_registration() -> None:
    @asynccontextmanager
    async def guard() -> AsyncIterator[None]:
        yield

    with pytest.raises(RuntimeError, match="handler failed"):
        async with OperationBoundary() as boundary:
            transaction = handler_transaction_view(FakeUnitOfWork([]), boundary)
            raise RuntimeError("handler failed")
    with pytest.raises(ConfigurationError):
        defer_handler_completion(transaction, guard)


@pytest.mark.asyncio
async def test_sequential_only_authorizer_cannot_supply_ui_final_authority() -> None:
    class LegacyPolicy:
        async def is_allowed(
            self, principal_id: UUID, tenant: TenantContext, permission: str
        ) -> bool:
            return True

    context = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=uuid4(),
            principal_id=uuid4(),
        )
    )
    authorizer = Authorizer(LegacyPolicy())
    await authorizer.require(context, "foundation.metadata.ui.read")
    with pytest.raises(BusinessOSError, match="Coherent Policy authority required"):
        async with authorizer.permission_fence(
            context,
            frozenset({"foundation.metadata.ui.read"}),
            cast(TransactionalPersistence, FakeUnitOfWork([])),
        ):
            pytest.fail("Legacy independent checks must not release protected UI results")
