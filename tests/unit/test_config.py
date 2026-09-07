import pytest
from pydantic import ValidationError

from businessos.config import Settings


def test_settings_require_psycopg_sqlalchemy_dialect() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(database_url="sqlite+aiosqlite://")


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=0)


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
