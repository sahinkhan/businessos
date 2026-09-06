"""Public transaction-bound persistence contracts for module-owned repositories."""

from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy.engine import Result
from sqlalchemy.sql.base import Executable


class TransactionalPersistence(Protocol):
    """Restricted access to the active Unit-of-Work transaction.

    Modules may execute statements for tables they own, but transaction completion
    remains exclusively controlled by the framework Unit of Work.
    """

    async def execute(
        self,
        statement: Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Result[Any]: ...

    async def flush(self) -> None: ...
