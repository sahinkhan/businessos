"""Structured JSON logging with framework context correlation."""

import json
import logging
from datetime import UTC, datetime

from businessos.context import current_request_context


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter using only standard logging contracts."""

    def format(self, record: logging.LogRecord) -> str:
        context = current_request_context()
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if context is not None:
            payload["correlation_id"] = context.correlation_id
            payload["trace_id"] = context.trace_id
            if context.tenant is not None:
                payload["tenant_id"] = str(context.tenant.tenant_id)
        if record.exc_info:
            exception_type = record.exc_info[0]
            payload["exception_type"] = (
                exception_type.__name__ if exception_type is not None else "Exception"
            )
        error_type = getattr(record, "error_type", None)
        if isinstance(error_type, str):
            payload["error_type"] = error_type
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: str) -> None:
    """Configure process logging exactly once from validated settings."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
