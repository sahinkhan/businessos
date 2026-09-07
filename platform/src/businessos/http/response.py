"""BusinessOS HTTP response abstraction."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Self
from uuid import UUID

from asgiref.typing import ASGISendCallable, HTTPResponseStartEvent
from pydantic import BaseModel


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@dataclass(slots=True)
class Response:
    status_code: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def text(
        cls,
        content: str,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Self:
        merged = {"content-type": "text/plain; charset=utf-8", **dict(headers or {})}
        return cls(status_code=status_code, body=content.encode(), headers=merged)

    @classmethod
    def json(
        cls,
        content: object,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Self:
        if isinstance(content, BaseModel):
            content = content.model_dump(mode="json")
        merged = {"content-type": "application/json", **dict(headers or {})}
        return cls(
            status_code=status_code,
            body=json.dumps(content, separators=(",", ":"), default=_json_default).encode(),
            headers=merged,
        )

    async def send(self, send: ASGISendCallable) -> None:
        start: HTTPResponseStartEvent = {
            "type": "http.response.start",
            "status": self.status_code,
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in self.headers.items()
            ],
            "trailers": False,
        }
        await send(start)
        await send({"type": "http.response.body", "body": self.body, "more_body": False})
