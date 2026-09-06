import pytest
from pydantic import ValidationError

from businessos.config import Settings


def test_settings_require_psycopg_sqlalchemy_dialect() -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(database_url="sqlite+aiosqlite://")


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=0)
