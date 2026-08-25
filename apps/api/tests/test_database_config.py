from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.persistence.database import Settings, database_backend
from app.persistence.runtime_secrets import (
    initialize_provider_secret,
    initialize_runtime_secrets,
)


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


def test_runtime_secret_files_are_loaded_and_direct_values_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    database_url = "postgresql+asyncpg://agent_studio:placeholder@db:5432/agent_studio"
    database_file = tmp_path / "database_url"
    database_file.write_text(f"  {database_url}\n", encoding="utf-8")
    provider_file = tmp_path / "deepseek_api_key"
    provider_file.write_text("  runtime-only-value\n", encoding="utf-8")

    configured = Settings(
        _env_file=None,
        database_url_file=database_file,
        deepseek_api_key_file=provider_file,
        llm_provider="deepseek",
        require_llm_provider_configured=True,
    )

    assert configured.database_url == database_url
    assert configured.deepseek_api_key == "runtime-only-value"
    assert "runtime-only-value" not in repr(configured)

    direct_secret = "DUMMY-CONFLICT-SECRET-NEVER-LOG"
    with pytest.raises(ValidationError, match="Configure only one") as captured:
        Settings(
            _env_file=None,
            deepseek_api_key=direct_secret,
            deepseek_api_key_file=provider_file,
        )
    assert direct_secret not in str(captured.value)
    assert direct_secret[:12] not in str(captured.value)


@pytest.mark.parametrize("content", ["", "  \r\n"])
def test_runtime_secret_file_rejects_empty_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    secret_file = tmp_path / "empty"
    secret_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValidationError, match="must not be empty"):
        Settings(_env_file=None, deepseek_api_key_file=secret_file)


def test_runtime_secret_file_failures_never_echo_secret_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    secret = "do-not-echo-this-runtime-secret"
    oversized = tmp_path / "oversized"
    oversized.write_text(secret * 4_000, encoding="utf-8")

    with pytest.raises(ValidationError) as captured:
        Settings(_env_file=None, deepseek_api_key_file=oversized)
    assert "64 KiB" in str(captured.value)
    assert secret not in str(captured.value)

    with pytest.raises(ValidationError, match="regular file"):
        Settings(_env_file=None, deepseek_api_key_file=tmp_path / "missing")


def test_required_provider_configuration_fails_closed_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    unselected_secret = "DUMMY-UNSELECTED-SECRET-NEVER-LOG"

    with pytest.raises(ValidationError, match="OpenAI API key is not configured") as captured:
        Settings(
            _env_file=None,
            llm_provider="openai",
            deepseek_api_key=unselected_secret,
            require_llm_provider_configured=True,
        )
    assert unselected_secret not in str(captured.value)
    assert unselected_secret[:12] not in str(captured.value)


def test_database_runtime_secret_initialization_is_idempotent(tmp_path: Path) -> None:
    initialize_runtime_secrets(
        tmp_path,
        database_host="db",
        database_port=5432,
        database_name="agent_studio",
        database_user="agent_studio",
    )
    first_password = (tmp_path / "postgres_password").read_text(encoding="utf-8")
    initialize_runtime_secrets(
        tmp_path,
        database_host="db",
        database_port=5432,
        database_name="agent_studio",
        database_user="agent_studio",
    )

    assert (tmp_path / "postgres_password").read_text(encoding="utf-8") == first_password
    url = make_url((tmp_path / "database_url").read_text(encoding="utf-8"))
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db"
    assert url.database == "agent_studio"
    assert url.username == "agent_studio"
    assert url.password == first_password


def test_provider_secret_initialization_keeps_only_selected_key(tmp_path: Path) -> None:
    initialize_provider_secret(
        tmp_path,
        provider="openai",
        secret="  openai-runtime-only\n",
    )
    initialize_provider_secret(
        tmp_path,
        provider="deepseek",
        secret="deepseek-runtime-only\n",
    )

    assert not (tmp_path / "openai_api_key").exists()
    assert (tmp_path / "deepseek_api_key").read_text(
        encoding="utf-8"
    ) == "deepseek-runtime-only"


@pytest.mark.parametrize("secret", ["", " \r\n", "bad\x00value"])
def test_provider_secret_initialization_rejects_invalid_text(
    tmp_path: Path, secret: str
) -> None:
    with pytest.raises(ValueError, match="non-empty UTF-8"):
        initialize_provider_secret(tmp_path, provider="deepseek", secret=secret)


@pytest.mark.parametrize(
    ("database_name", "database_user", "database_host", "database_port", "message"),
    [
        ("", "agent_studio", "db", 5432, "POSTGRES_DB"),
        ("agent_studio", "", "db", 5432, "POSTGRES_USER"),
        ("agent_studio", "agent_studio", "", 5432, "DATABASE_HOST"),
        ("agent_studio", "agent_studio", "db", 0, "DATABASE_PORT"),
    ],
)
def test_database_runtime_secret_configuration_is_validated(
    tmp_path: Path,
    database_name: str,
    database_user: str,
    database_host: str,
    database_port: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        initialize_runtime_secrets(
            tmp_path,
            database_host=database_host,
            database_port=database_port,
            database_name=database_name,
            database_user=database_user,
        )
