"""ADR-024 private publication dispatch, without privileged handler persistence.

The composition root installs fixed, approved owner adapters. Commands supply
authoring intent only. Neither the registered handler nor a caller callback runs
inside the private transaction. Audit gets a fixed append operation, not SQL.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy.engine import Result
from sqlalchemy.sql.base import Executable

from businessos.activation import ContributionGate
from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.handler_invocation import HandlerInvocationKind, internal_issue_handler_invocation
from businessos.messages import (
    Command,
    HandlerTransaction,
    HandlingContext,
    _OwnedHandler,  # pyright: ignore[reportPrivateUsage] -- exact kernel enrollment
    handler_transaction_view,
)
from businessos.metadata import AdmittedMetadataDeclaration, MetadataCatalog
from businessos.operation_boundary import OperationBoundary, bind_handler_boundary
from businessos.persistence import PendingOutboxMessage, TransactionalPersistence
from businessos.publication_database import PublicationDatabaseAuthority
from businessos.resources import ResourceTransactionScope


class PublicationOwnerWriter(Protocol):
    async def view(self, message: Command, context: HandlingContext) -> UUID: ...

    async def execute(
        self,
        message: Command,
        context: HandlingContext,
        sources: tuple[AdmittedMetadataDeclaration, ...],
    ) -> object: ...


class PublicationAuditWriter(Protocol):
    async def __call__(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        evidence: object,
        provenance: dict[str, Any],
    ) -> object: ...


class _NoPublicationSQL:
    async def execute(
        self,
        statement: Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Result[Any]:
        raise PermissionError(
            "Private publication persistence is unavailable to handlers/providers"
        )

    async def flush(self) -> None:
        raise PermissionError(
            "Private publication persistence is unavailable to handlers/providers"
        )


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class _PublicationTransaction:
    persistence: TransactionalPersistence = field(default_factory=_NoPublicationSQL)

    def add_outbox(self, message: PendingOutboxMessage) -> None:
        state = _state(self)
        if state.request.tenant is None or message.tenant_id != state.request.tenant.tenant_id:
            raise PermissionError("Publication outbox tenant mismatch")
        state.transaction.add_outbox(message)


@dataclass(frozen=True, slots=True)
class _PublicationState:
    request: RequestContext
    transaction: HandlerTransaction
    audit_writer: PublicationAuditWriter


# Like issued invocation/completion capabilities, private state remains in the
# kernel registry, never as a persistence-bearing attribute of the context.
_transactions: WeakKeyDictionary[_PublicationTransaction, _PublicationState] = WeakKeyDictionary()


def _state(transaction: _PublicationTransaction) -> _PublicationState:
    result = _transactions.get(transaction)
    if result is None:
        raise PermissionError("Private publication transaction is no longer active")
    return result


async def internal_append_publication_audit(
    context: HandlingContext,
    evidence: object,
    provenance: dict[str, Any],
) -> object | None:
    """Fixed AuditAppenderV2 bridge; no persistence or arbitrary callback is returned."""
    transaction = context.unit_of_work
    if type(transaction) is not _PublicationTransaction:
        return None
    state = _state(transaction)
    if state.request is not context.request:
        raise PermissionError("Publication audit context mismatch")
    return await state.audit_writer(context.request, state.transaction, evidence, provenance)


class PrivatePublicationExecutor:
    def __init__(
        self,
        authority: PublicationDatabaseAuthority,
        catalog: MetadataCatalog,
        gate: ContributionGate,
        writer: Callable[[TransactionalPersistence], PublicationOwnerWriter],
        audit_writer: PublicationAuditWriter,
    ) -> None:
        self.authority = authority
        self._catalog = catalog
        self._gate = gate
        self._writer = writer
        self._audit_writer = audit_writer

    async def execute(
        self,
        registered: _OwnedHandler,
        message: Command,
        request: RequestContext,
        dependencies: RequestDependencyScope,
        boundary: OperationBoundary,
    ) -> object:
        if registered.generation is None or registered.direct_dependencies is None:
            raise PermissionError("Private publication requires admitted handler provenance")
        async with self.authority.for_command(registered, type(message), request.tenant) as unit:
            async with ResourceTransactionScope(
                self._gate,
                request,
                registered.owner,
                registered.generation,
                registered.coordinator_token,
            ) as resources:
                async with unit:
                    transaction = _PublicationTransaction()
                    _transactions[transaction] = _PublicationState(
                        request,
                        handler_transaction_view(unit),
                        self._audit_writer,
                    )
                    try:
                        bind_handler_boundary(transaction, boundary)
                        resources.bind_transaction(transaction)
                        context = HandlingContext(request, dependencies, transaction)
                        with internal_issue_handler_invocation(
                            owner_module_id=registered.owner,
                            generation=registered.generation,
                            invocation_kind=HandlerInvocationKind.COMMAND,
                            direct_dependencies=registered.direct_dependencies,
                            request=request,
                            transaction=transaction,
                        ) as invocation:
                            context.invocation = invocation
                            writer = self._writer(unit.persistence)
                            view = await writer.view(message, context)
                            sources = await self._catalog.retain_for_operation(
                                transaction,
                                kind_prefix="ui.",
                                discriminator="view_id",
                                value=str(view),
                            )
                            result = await writer.execute(message, context, sources)
                            await boundary.complete()
                            await unit.commit()
                            return result
                    finally:
                        _transactions.pop(transaction, None)
