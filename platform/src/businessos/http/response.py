"""BusinessOS HTTP response abstraction."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self

from asgiref.typing import ASGISendCallable, HTTPResponseStartEvent
from pydantic import BaseModel


@dataclass(slots=True)
class Response:
    status_code: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

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
            body=json.dumps(content, separators=(",", ":"), default=str).encode(),
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
