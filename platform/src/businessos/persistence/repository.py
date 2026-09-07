"""SDK 0.2 repository operations: data only, never executable SQL or driver results."""

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import column, table
from sqlalchemy.dialects.postgresql import insert

from businessos.errors import ConfigurationError
from businessos.persistence.contracts import TransactionalPersistence

# Closed boundary: subclasses with SQL compiler hooks are not accepted.
type Value = str | int | bool | bytes | UUID | Decimal | date | datetime | None
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class Repository(Protocol):
    async def select(
        self,
        name: str,
        columns: Sequence[str],
        *,
        where: Mapping[str, Value] | None = None,
        order_by: Sequence[str] = (),
        descending: bool = False,
        limit: int = 100,
    ) -> tuple[Mapping[str, Value], ...]: ...

    async def insert(
        self,
        name: str,
        values: Mapping[str, Value],
        *,
        conflict: Sequence[str] = (),
    ) -> bool: ...

    async def update(
        self,
        name: str,
        values: Mapping[str, Value],
        *,
        where: Mapping[str, Value],
    ) -> None: ...


def _identifier(value: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise ConfigurationError("Invalid repository identifier")
    return value


def _values(values: Mapping[str, Value]) -> dict[str, Value]:
    result: dict[str, Value] = {}
    for key, value in values.items():
        _identifier(key)
        if type(value) not in {str, int, bool, bytes, UUID, Decimal, date, datetime, type(None)}:
            raise ConfigurationError("Repository values must be plain data")
        result[key] = value
    return result


class TenantRepository:
    """Framework-created, owner and tenant-bound repository capability."""

    __slots__ = ("__check", "__persistence", "__schema", "__tenant_id")

    def __init__(
        self,
        persistence: Callable[[], TransactionalPersistence],
        owner: str,
        tenant_id: UUID,
        check: Callable[[], None],
    ) -> None:
        self.__persistence = persistence
        self.__check = check
        self.__schema = _identifier("mod_" + owner.replace(".", "_").replace("-", "_"))
        self.__tenant_id = tenant_id

    def _where(self, values: Mapping[str, Value] | None) -> dict[str, Value]:
        self.__check()
        result = _values(values or {})
        if "tenant_id" in result and result["tenant_id"] != self.__tenant_id:
            raise ConfigurationError("Repository tenant does not match trusted context")
        result["tenant_id"] = self.__tenant_id
        return result

    async def select(
        self,
        name: str,
        columns: Sequence[str],
        *,
        where: Mapping[str, Value] | None = None,
        order_by: Sequence[str] = (),
        descending: bool = False,
        limit: int = 100,
    ) -> tuple[Mapping[str, Value], ...]:
        from sqlalchemy import select

        if type(limit) is not int or not 1 <= limit <= 1000 or not columns:
            raise ConfigurationError("Repository query requires bounded results")
        filters = self._where(where)
        names = tuple(dict.fromkeys((*columns, *order_by, *filters)))
        relation = table(
            _identifier(name), *(column(_identifier(n)) for n in names), schema=self.__schema
        )
        statement = select(*(relation.c[n] for n in columns))
        for key, value in filters.items():
            statement = statement.where(relation.c[key] == value)
        for key in order_by:
            statement = statement.order_by(
                relation.c[key].desc() if descending else relation.c[key].asc()
            )
        result = await self.__persistence().execute(statement.limit(limit))
        return tuple(_values(dict(row)) for row in result.mappings().all())

    async def insert(
        self,
        name: str,
        values: Mapping[str, Value],
        *,
        conflict: Sequence[str] = (),
    ) -> bool:
        data = self._where(values)
        relation = table(_identifier(name), *(column(n) for n in data), schema=self.__schema)
        statement = insert(relation).values(**data)
        if conflict:
            for key in conflict:
                _identifier(key)
            if "tenant_id" not in conflict:
                raise ConfigurationError("Conflict identity must include tenant")
            statement = statement.on_conflict_do_nothing(index_elements=list(conflict))
        result = await self.__persistence().execute(statement.returning(relation.c.tenant_id))
        return result.first() is not None

    async def update(
        self,
        name: str,
        values: Mapping[str, Value],
        *,
        where: Mapping[str, Value],
    ) -> None:
        data = _values(values)
        if "tenant_id" in data:
            raise ConfigurationError("Tenant identity is immutable")
        if not where:
            raise ConfigurationError("Updates require an explicit record filter")
        filters = self._where(where)
        names = tuple(dict.fromkeys((*data, *filters)))
        relation = table(_identifier(name), *(column(n) for n in names), schema=self.__schema)
        statement = relation.update().values(**data)
        for key, value in filters.items():
            statement = statement.where(relation.c[key] == value)
        await self.__persistence().execute(statement)
