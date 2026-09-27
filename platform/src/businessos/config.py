"""Validated BusinessOS runtime configuration."""

from functools import lru_cache
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_serializer, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


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
    installation_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    database_url: str = Field(
        default=(
            "postgresql+psycopg://businessos_app:businessos-application@localhost:5432/businessos"
        ),
        repr=False,
        exclude=True,
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    governance_database_url: str | None = Field(default=None, repr=False, exclude=True)
    governance_database_pool_size: int = Field(default=2, ge=1, le=20)
    governance_database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_connection_budget: int = Field(default=100, ge=1)
    database_app_processes: int = Field(default=1, ge=1)
    database_worker_pool_reservation: int = Field(default=5, ge=0)
    database_ops_pool_reservation: int = Field(default=2, ge=0)
    database_other_connection_reservation: int = Field(default=10, ge=0)
    database_readiness_enabled: bool = True
    request_body_limit_bytes: int = Field(default=1_048_576, ge=1)
    startup_timeout_seconds: float = Field(default=30.0, gt=0)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0)
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region_name: str | None = None
    s3_access_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_secret_key: str | None = Field(default=None, repr=False, exclude=True)
    s3_provision_bucket: bool = False

    @model_validator(mode="after")
    def validate_database_driver(self) -> Self:
        required_connections = (
            self.database_pool_size * self.database_app_processes
            + (
                self.governance_database_pool_size * self.database_app_processes
                if self.governance_database_url is not None
                else 0
            )
            + self.database_worker_pool_reservation
            + self.database_ops_pool_reservation
            + self.database_other_connection_reservation
        )
        if required_connections > self.database_connection_budget:
            raise ValueError("Configured database pools exceed the installation connection budget")
        if not self.database_url.startswith("postgresql+psycopg://"):
            msg = "database_url must use the postgresql+psycopg SQLAlchemy dialect"
            raise ValueError(msg)
        if self.governance_database_url is not None:
            if not self.governance_database_url.startswith("postgresql+psycopg://"):
                raise ValueError("governance_database_url must use the psycopg dialect")
            ordinary = make_url(self.database_url)
            protected = make_url(self.governance_database_url)
            if (
                protected.username != "businessos_governance"
                or ordinary.database != protected.database
                or ordinary.host != protected.host
                or ordinary.port != protected.port
            ):
                raise ValueError(
                    "Governance profile must target the same database with its dedicated role"
                )
        if (self.s3_access_key is None) != (self.s3_secret_key is None):
            raise ValueError("S3 access key and secret key must be configured together")
        storage_options = (
            self.s3_endpoint_url,
            self.s3_region_name,
            self.s3_access_key,
            self.s3_secret_key,
        )
        if self.s3_bucket is None and (any(storage_options) or self.s3_provision_bucket):
            raise ValueError("S3 bucket is required when object-storage options are configured")
        if self.environment == "production" and self.s3_provision_bucket:
            raise ValueError("Production object-storage buckets must be provisioned externally")
        return self

    @field_serializer("database_url")
    def serialize_database_url(self, _: str) -> str:
        return "**********"

    @field_serializer("governance_database_url")
    def serialize_governance_database_url(self, _: str | None) -> str:
        return "**********"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""
    return Settings()
