"""Validated BusinessOS runtime configuration."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings loaded once by the composition root."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BOS_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_version: str | None = None
    database_url: str = (
        "postgresql+psycopg://businessos_app:businessos-application@localhost:5432/businessos"
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_readiness_enabled: bool = True
    request_body_limit_bytes: int = Field(default=1_048_576, ge=1)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def validate_database_driver(self) -> Self:
        if not self.database_url.startswith("postgresql+psycopg://"):
            msg = "database_url must use the postgresql+psycopg SQLAlchemy dialect"
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
