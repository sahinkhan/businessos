"""Validate a broker delivery against the committed platform outbox source."""

import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, text

from businessos.persistence import OutboxMessage, SQLAlchemyUnitOfWorkFactory
from businessos.providers import PermanentDeliveryError


def strict_event_payload(payload: bytes) -> dict[str, object]:
    """Reject ambiguous JSON before any Pydantic event decoding."""

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        decoded = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
        if not isinstance(decoded, dict):
            raise ValueError("event payload must be an object")
        # Surrogates and non-JSON numeric values cannot have a canonical UTF-8 form.
        json.dumps(decoded, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return cast(dict[str, object], decoded)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PermanentDeliveryError("Invalid event envelope") from exc


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class CommittedOutboxSourceVerifier:
    """Only the isolated operations role can read source rows across tenants."""

    def __init__(self, operations_uow: SQLAlchemyUnitOfWorkFactory) -> None:
        self._operations_uow = operations_uow

    async def verify(
        self,
        *,
        event_id: UUID,
        tenant_id: UUID,
        event_type: str,
        schema_version: int,
        occurred_at: datetime,
        correlation_id: str,
        causation_id: str | None,
        payload: dict[str, object],
    ) -> None:
        async with self._operations_uow.system() as unit_of_work:
            await unit_of_work.persistence.execute(text("SET TRANSACTION READ ONLY"))
            result = await unit_of_work.persistence.execute(
                select(OutboxMessage).where(OutboxMessage.id == event_id)
            )
            source = result.scalar_one_or_none()
            if (
                source is None
                or source.id != event_id
                or source.tenant_id != tenant_id
                or source.event_type != event_type
                or source.schema_version != schema_version
                or source.occurred_at != occurred_at
                or source.correlation_id != correlation_id
                or source.causation_id != causation_id
                or _canonical(source.payload) != _canonical(payload)
            ):
                raise PermanentDeliveryError("Event does not match committed source")
