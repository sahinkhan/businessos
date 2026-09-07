"""Validated BusinessOS runtime configuration."""

from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_serializer, model_validator
from pydantic_settings import SettingsConfigDict

from businessos.secure_settings import SafeSettings


class Settings(SafeSettings):
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
    database_url: str = Field(
        default=(
            "postgresql+psycopg://businessos_app:businessos-application@localhost:5432/businessos"
        ),
        repr=False,
        exclude=True,
    )
    tenant_database_urls: dict[UUID, str] = Field(default_factory=dict, repr=False, exclude=True)
    maximum_tenant_pools: int = Field(default=100, ge=1, le=10000)
    disabled_modules: tuple[str, ...] = ()
    context_resolver_factory: str | None = None
    policy_evaluator_factory: str | None = None
    redis_url: str | None = Field(default=None, repr=False, exclude=True)
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = Field(default=None, repr=False, exclude=True)
    s3_access_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_secret_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_provision_bucket: bool = False

    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_readiness_enabled: bool = True
    request_body_limit_bytes: int = Field(default=1_048_576, ge=1)
    startup_timeout_seconds: float = Field(default=30.0, gt=0)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def validate_database_driver(self) -> Self:
        if not self.database_url.startswith("postgresql+psycopg://"):
            msg = "database_url must use the postgresql+psycopg SQLAlchemy dialect"
            raise ValueError(msg)
        return self

    @field_serializer("database_url")
    def serialize_database_url(self, _: str) -> str:
        return "**********"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
