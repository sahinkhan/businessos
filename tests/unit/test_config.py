import pytest
from pydantic import ValidationError

from businessos.bootstrap import configured_infrastructure_providers
from businessos.config import Settings


def test_settings_require_psycopg_sqlalchemy_dialect() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(database_url="sqlite+aiosqlite://")


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=0)


def test_database_pool_budget_counts_protected_and_reserved_connections() -> None:
    with pytest.raises(ValidationError, match="connection budget"):
        Settings(
            database_url="postgresql+psycopg://businessos_app:secret@localhost:5432/businessos",
            governance_database_url=(
                "postgresql+psycopg://businessos_governance:secret@localhost:5432/businessos"
            ),
            database_connection_budget=20,
            database_app_processes=2,
        )
    settings = Settings(
        database_url="postgresql+psycopg://businessos_app:secret@localhost:5432/businessos",
        governance_database_url=(
            "postgresql+psycopg://businessos_governance:secret@localhost:5432/businessos"
        ),
        database_connection_budget=31,
        database_app_processes=2,
    )
    assert settings.database_connection_budget == 31


def test_database_url_is_redacted_from_settings_representations() -> None:
    secret = "never-print-database-password"
    settings = Settings(
        database_url=f"postgresql+psycopg://businessos_app:{secret}@database/businessos"
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert settings.database_url.endswith(f":{secret}@database/businessos")
    assert secret not in str(settings.model_dump())
    assert "database_url" not in settings.model_dump()


def test_object_storage_credentials_are_validated_and_redacted() -> None:
    secret = "never-print-object-storage-secret"
    settings = Settings(
        s3_bucket="businessos",
        s3_access_key="access-key",
        s3_secret_key=secret,
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert "s3_secret_key" not in settings.model_dump()
    with pytest.raises(ValidationError, match="configured together"):
        Settings(s3_bucket="businessos", s3_access_key="incomplete")
    with pytest.raises(ValidationError, match="bucket is required"):
        Settings(s3_endpoint_url="https://objects.example.test")


def test_development_composition_supplies_real_object_storage_provider() -> None:
    providers = configured_infrastructure_providers(Settings(environment="development"))

    assert tuple(providers) == ("object-storage",)


def test_production_composition_fails_closed_without_storage_configuration() -> None:
    settings = Settings(environment="production")

    assert configured_infrastructure_providers(settings) == {}
    with pytest.raises(ValidationError, match="provisioned externally"):
        Settings(
            environment="production",
            s3_bucket="businessos",
            s3_provision_bucket=True,
        )


def test_metadata_profile_credentials_are_scoped_redacted_and_budgeted() -> None:
    ordinary = "postgresql+psycopg://businessos_app:app@db:5432/businessos"
    protected = "postgresql+psycopg://businessos_metadata:metadata-secret@db:5432/businessos"
    settings = Settings(database_url=ordinary, metadata_database_url=protected)
    assert "metadata-secret" not in repr(settings)
    assert "metadata_database_url" not in settings.model_dump()
    for invalid in (
        protected.replace("businessos_metadata", "businessos_app"),
        protected.replace("@db:", "@other:"),
        protected.replace("/businessos", "/other"),
    ):
        with pytest.raises(ValidationError, match="dedicated role"):
            Settings(database_url=ordinary, metadata_database_url=invalid)
    with pytest.raises(ValidationError, match="connection budget"):
        Settings(
            database_url=ordinary, metadata_database_url=protected, database_connection_budget=23
        )
