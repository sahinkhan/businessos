"""Credential-safe boundary for environment parsing and configuration validation."""

from typing import Any, NoReturn, Self

from pydantic import ValidationError
from pydantic_settings import BaseSettings


class SafeSettings(BaseSettings):
    """Never retain invalid input or provider exceptions in public settings errors."""

    def __init__(self, **values: Any) -> None:
        failed = False
        try:
            super().__init__(**values)
        except Exception:
            failed = True
        # Raise outside the except block: even __context__ must not retain inputs.
        if failed:
            values.clear()
            self.__dict__.clear()
            raise ValidationError.from_exception_data(
                type(self).__name__,
                [
                    {
                        "type": "value_error",
                        "loc": (),
                        "input": "[redacted]",
                        "ctx": {"error": ValueError("Invalid runtime configuration")},
                    }
                ],
                hide_input=True,
            )

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "Self":
        failed = False
        try:
            result = super().model_validate(obj, **kwargs)
        except Exception:
            failed = True
        if failed:
            obj = None
            kwargs.clear()
            cls._invalid()
        return result

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> "Self":
        failed = False
        try:
            result = super().model_validate_json(json_data, **kwargs)
        except Exception:
            failed = True
        if failed:
            json_data = "[redacted]"
            kwargs.clear()
            cls._invalid()
        return result

    @classmethod
    def model_validate_strings(cls, obj: Any, **kwargs: Any) -> "Self":
        failed = False
        try:
            result = super().model_validate_strings(obj, **kwargs)
        except Exception:
            failed = True
        if failed:
            obj = None
            kwargs.clear()
            cls._invalid()
        return result

    @classmethod
    def _invalid(cls) -> "NoReturn":
        raise ValidationError.from_exception_data(
            cls.__name__,
            [
                {
                    "type": "value_error",
                    "loc": (),
                    "input": "[redacted]",
                    "ctx": {"error": ValueError("Invalid runtime configuration")},
                }
            ],
            hide_input=True,
        )
