"""Read-only canonical Currency foundation module."""

import json
from importlib.resources import files

from pydantic import Field
from sqlalchemy import select

from businessos.sdk import (
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
)

from .contracts import CurrencyReadContract, CurrencyRecord
from .models import CURRENCIES


class GetCurrency(Query):
    code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class ResolveCurrency(Query):
    code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class ListCurrencies(Query):
    active_only: bool = True
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class CurrencyModule:
    def __init__(self) -> None:
        raw = files("businessos_currency").joinpath("manifest.json").read_text(encoding="utf-8")
        self.manifest = ModuleManifest.model_validate(json.loads(raw))
        self.read_contract = CurrencyReadContract()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.currency.read", description="Read canonical currency data"
            )
        )
        registration.contract("foundation.currency.read.v1", self.read_contract)
        registration.query(GetCurrency, self._get, permission="foundation.currency.read")
        registration.query(ResolveCurrency, self._get, permission="foundation.currency.read")
        registration.query(ListCurrencies, self._list, permission="foundation.currency.read")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _get(
        self, query: GetCurrency | ResolveCurrency, context: HandlingContext
    ) -> CurrencyRecord | None:
        persistence = context.unit_of_work.persistence
        row = (
            await persistence.execute(select(CURRENCIES).where(CURRENCIES.c.code == query.code))
        ).first()
        return None if row is None else _record(row)

    async def _list(self, query: ListCurrencies, context: HandlingContext) -> list[CurrencyRecord]:
        statement = select(CURRENCIES)
        if query.active_only:
            statement = statement.where(CURRENCIES.c.is_active.is_(True))
        statement = statement.order_by(CURRENCIES.c.code).limit(query.limit).offset(query.offset)
        persistence = context.unit_of_work.persistence
        rows = (await persistence.execute(statement)).fetchall()
        return [_record(row) for row in rows]


def _record(row: object) -> CurrencyRecord:
    return CurrencyRecord(
        id=row.id,  # type: ignore[attr-defined]
        code=row.code,  # type: ignore[attr-defined]
        numeric_code=row.numeric_code,  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        minor_unit=row.minor_unit,  # type: ignore[attr-defined]
        is_active=row.is_active,  # type: ignore[attr-defined]
        source=row.source,  # type: ignore[attr-defined]
        source_version=row.source_version,  # type: ignore[attr-defined]
    )
