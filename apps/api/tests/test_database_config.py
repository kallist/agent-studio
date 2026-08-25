from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import ArgumentError

from app.persistence.database import Settings, database_backend


def test_settings_without_database_url_defaults_to_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    configured = Settings(_env_file=None)

    assert configured.database_url == "sqlite+aiosqlite:///./agent_studio.db"
    assert database_backend(configured.database_url) == "sqlite"
    assert configured.llm_provider == "openai"
    assert configured.deepseek_model == "deepseek-v4-flash"
    assert configured.deepseek_base_url == "https://api.deepseek.com"


def test_model_provider_and_deepseek_origin_are_validated_fail_closed() -> None:
    configured = Settings(
        _env_file=None,
        llm_provider=" DEEPSEEK ",
        deepseek_base_url="https://api.deepseek.com/",
    )
    assert configured.llm_provider == "deepseek"
    assert configured.deepseek_base_url == "https://api.deepseek.com"

    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(_env_file=None, llm_provider="mock")
    with pytest.raises(ValidationError, match="official"):
        Settings(_env_file=None, deepseek_base_url="http://127.0.0.1:8080")
    with pytest.raises(ValidationError, match="official"):
        Settings(_env_file=None, deepseek_base_url="https://example.com")


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
