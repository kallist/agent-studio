from __future__ import annotations

import pytest
from sqlalchemy.exc import ArgumentError

from app.persistence.database import Settings, database_backend


def test_settings_without_database_url_defaults_to_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    configured = Settings(_env_file=None)

    assert configured.database_url == "sqlite+aiosqlite:///./agent_studio.db"
    assert database_backend(configured.database_url) == "sqlite"


def test_database_backend_selection_is_explicit_and_url_driven() -> None:
    assert database_backend("sqlite+aiosqlite:///./agent_studio.db") == "sqlite"
    assert (
        database_backend(
            "postgresql+asyncpg://example_test:placeholder@127.0.0.1:55432/example_test"
        )
        == "postgresql"
    )


def test_malformed_database_url_fails_configuration() -> None:
    with pytest.raises(ArgumentError):
        database_backend(":// malformed database url")


@pytest.mark.parametrize(
    "database_url",
    [
        "mysql+asyncmy://example_test:placeholder@127.0.0.1/example_test",
        "postgresql+psycopg://example_test:placeholder@127.0.0.1/example_test",
        "sqlite+pysqlite:///./agent_studio.db",
    ],
)
def test_unsupported_backend_or_driver_fails_closed(database_url: str) -> None:
    with pytest.raises(ValueError, match=r"sqlite\+aiosqlite or postgresql\+asyncpg"):
        database_backend(database_url)
