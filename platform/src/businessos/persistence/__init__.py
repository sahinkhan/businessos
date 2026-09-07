"""Framework-owned PostgreSQL persistence contracts and implementations."""

from businessos.persistence.contracts import TransactionalPersistence
from businessos.persistence.database import Database
from businessos.persistence.models import (
    Base,
    EventSubscriberObligation,
    InboxReceipt,
    ModuleRuntimeState,
    OutboxMessage,
)
from businessos.persistence.outbox import PendingOutboxMessage
from businessos.persistence.uow import (
    SQLAlchemyUnitOfWork,
    SQLAlchemyUnitOfWorkFactory,
    UnitOfWork,
    UnitOfWorkFactory,
)

__all__ = [
    "Base",
    "Database",
    "EventSubscriberObligation",
    "InboxReceipt",
    "ModuleRuntimeState",
    "OutboxMessage",
    "PendingOutboxMessage",
    "SQLAlchemyUnitOfWork",
    "SQLAlchemyUnitOfWorkFactory",
    "TransactionalPersistence",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
