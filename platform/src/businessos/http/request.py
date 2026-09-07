"""Transport-neutral request abstraction backed internally by ASGI."""

import json
from collections.abc import Mapping
from urllib.parse import parse_qs

from asgiref.typing import ASGIReceiveCallable, HTTPScope

from businessos.context import RequestContext
from businessos.errors import BusinessOSError, ClientDisconnectedError


class Request:
    """The only HTTP request object exposed to BusinessOS route handlers."""

    def __init__(
        self,
        scope: HTTPScope,
        receive: ASGIReceiveCallable,
        context: RequestContext,
        *,
        path_params: Mapping[str, str] | None = None,
        body_limit_bytes: int = 1_048_576,
    ) -> None:
        self._receive = receive
        self._body_limit_bytes = body_limit_bytes
        self._body: bytes | None = None
        self.method = scope["method"].upper()
        self.path = scope["path"]
        self.root_path = scope.get("root_path", "")
        self.scheme = scope.get("scheme", "http")
        self.context = context
        self.path_params = dict(path_params or {})
        self.headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        raw_query = scope.get("query_string", b"").decode("utf-8")
        self.query_params = {
            key: tuple(values)
            for key, values in parse_qs(raw_query, keep_blank_values=True).items()
        }

    async def body(self) -> bytes:
        if self._body is not None:
            return self._body
        chunks: list[bytes] = []
        size = 0
        more_body = True
        while more_body:
            message = await self._receive()
            if message["type"] == "http.disconnect":
                raise ClientDisconnectedError
            event = message
            if event["type"] != "http.request":
                continue
            request_event = event
            chunk = request_event.get("body", b"")
            size += len(chunk)
            if size > self._body_limit_bytes:
                raise BusinessOSError(
                    "request_too_large", "Request body exceeds configured limit", status_code=413
                )
            chunks.append(chunk)
            more_body = request_event.get("more_body", False)
        self._body = b"".join(chunks)
        return self._body

    async def json(self) -> object:
        try:
            return json.loads(await self.body())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BusinessOSError("invalid_json", "Request body is not valid JSON") from exc
