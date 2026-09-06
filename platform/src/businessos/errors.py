"""Stable framework error contracts."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict


class ErrorPayload(BaseModel):
    """Serialized public error body."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: Mapping[str, object] | None = None


class BusinessOSError(Exception):
    """Expected framework/application error with an HTTP-safe representation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def payload(self) -> ErrorPayload:
        return ErrorPayload(code=self.code, message=self.message, details=self.details)


class ConfigurationError(BusinessOSError):
    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message, status_code=500)


class NotFoundError(BusinessOSError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__("not_found", message, status_code=404)


class MethodNotAllowedError(BusinessOSError):
    def __init__(self, allowed_methods: tuple[str, ...]) -> None:
        super().__init__(
            "method_not_allowed",
            "Method not allowed",
            status_code=405,
            details={"allowed_methods": allowed_methods},
        )


class ConflictError(BusinessOSError):
    def __init__(self, message: str) -> None:
        super().__init__("conflict", message, status_code=409)
