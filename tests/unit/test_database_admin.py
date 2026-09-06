import psycopg
import pytest

from businessos.database_admin import (
    DatabaseRolePasswords,
    DatabaseTransitionError,
    transition_database_roles,
)


def test_role_transition_credentials_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    canary = "never-print-this-database-secret"
    passwords = DatabaseRolePasswords(
        migrator=canary,
        application=canary,
        operations=canary,
    )

    def fail_connect(*args: object, **kwargs: object) -> object:
        raise psycopg.OperationalError(f"connection failed with {canary}")

    monkeypatch.setattr(psycopg, "connect", fail_connect)

    assert canary not in repr(passwords)
    with pytest.raises(DatabaseTransitionError) as raised:
        transition_database_roles(f"postgresql://admin:{canary}@database/businessos", passwords)
    assert str(raised.value) == "database role transition failed"
    assert canary not in str(raised.value)
