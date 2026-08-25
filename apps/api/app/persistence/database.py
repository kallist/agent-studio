from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "production-like"] = "development"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./agent_studio.db", repr=False
    )
    database_url_file: Path | None = None
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_api_key_file: Path | None = None
    openai_model: str | None = None
    openai_agents_disable_tracing: bool = True
    openai_request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    openai_max_retries: int = Field(default=2, ge=0, le=5)
    openai_max_output_tokens: int = Field(default=512, ge=64, le=4_096)
    llm_provider: str = "openai"
    deepseek_api_key: str | None = Field(default=None, repr=False)
    deepseek_api_key_file: Path | None = None
    deepseek_model: str | None = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    deepseek_max_retries: int = Field(default=2, ge=0, le=5)
    deepseek_max_output_tokens: int = Field(default=512, ge=64, le=4_096)
    mock_provider_block_input: str | None = Field(default=None, max_length=200)
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    allowed_hosts: str = "127.0.0.1,localhost,test,testserver"
    knowledge_storage_path: str = "./data/knowledge"
    knowledge_max_file_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=50 * 1024 * 1024)
    knowledge_max_extracted_chars: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    knowledge_max_chunks: int = Field(default=5_000, ge=1, le=20_000)
    knowledge_parser_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    knowledge_worker_count: int = Field(default=1, ge=1, le=8)
    evaluation_worker_count: int = Field(default=1, ge=1, le=8)
    embedding_provider: str = "local"
    openai_embedding_model: str = "text-embedding-3-small"
    require_llm_provider_configured: bool = False

    @field_validator(
        "openai_api_key",
        "openai_model",
        "deepseek_api_key",
        "deepseek_model",
        mode="before",
    )
    @classmethod
    def normalize_optional_provider_settings(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in {"openai", "deepseek"}:
            raise ValueError("LLM_PROVIDER must be 'openai' or 'deepseek'.")
        return normalized

    @field_validator("deepseek_base_url")
    @classmethod
    def validate_deepseek_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.deepseek.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in {"", "/v1"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "DEEPSEEK_BASE_URL must use the official https://api.deepseek.com origin."
            )
        return normalized

    @field_validator("embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in {"local", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be 'local' or 'openai'.")
        return normalized

    @field_validator("cors_origins", "allowed_hosts")
    @classmethod
    def reject_unbounded_network_lists(cls, value: str) -> str:
        entries = [entry.strip() for entry in value.split(",") if entry.strip()]
        if not entries or "*" in entries:
            raise ValueError("Network origin and host lists must be explicit and non-empty.")
        return ",".join(entries)

    @model_validator(mode="after")
    def load_runtime_secret_files(self) -> Self:
        """Resolve optional runtime secret files without logging secret material."""

        resolved_database_url = self._resolve_secret_file(
            direct_name="DATABASE_URL",
            direct_value=self.database_url,
            file_name="DATABASE_URL_FILE",
            file_path=self.database_url_file,
            direct_was_configured="database_url" in self.model_fields_set,
        )
        if resolved_database_url is None:
            raise ValueError("DATABASE_URL configuration is required.")
        self.database_url = resolved_database_url
        self.openai_api_key = self._resolve_secret_file(
            direct_name="OPENAI_API_KEY",
            direct_value=self.openai_api_key,
            file_name="OPENAI_API_KEY_FILE",
            file_path=self.openai_api_key_file,
            direct_was_configured=self.openai_api_key is not None,
        )
        self.deepseek_api_key = self._resolve_secret_file(
            direct_name="DEEPSEEK_API_KEY",
            direct_value=self.deepseek_api_key,
            file_name="DEEPSEEK_API_KEY_FILE",
            file_path=self.deepseek_api_key_file,
            direct_was_configured=self.deepseek_api_key is not None,
        )

        if self.require_llm_provider_configured:
            selected_key = (
                self.openai_api_key
                if self.llm_provider == "openai"
                else self.deepseek_api_key
            )
            if not selected_key:
                provider_name = "OpenAI" if self.llm_provider == "openai" else "DeepSeek"
                raise ValueError(f"{provider_name} API key is not configured.")
        return self

    @staticmethod
    def _resolve_secret_file(
        *,
        direct_name: str,
        direct_value: str | None,
        file_name: str,
        file_path: Path | None,
        direct_was_configured: bool,
    ) -> str | None:
        if file_path is None:
            return direct_value
        if direct_was_configured:
            raise ValueError(f"Configure only one of {direct_name} and {file_name}.")

        try:
            if not file_path.is_file():
                raise ValueError(f"{file_name} must reference a readable regular file.")
            if file_path.stat().st_size > 64 * 1024:
                raise ValueError(f"{file_name} exceeds the 64 KiB secret-file limit.")
            secret = file_path.read_text(encoding="utf-8").strip()
        except UnicodeError as exc:
            raise ValueError(f"{file_name} must contain UTF-8 text.") from exc
        except OSError as exc:
            raise ValueError(f"{file_name} could not be read.") from exc

        if not secret:
            raise ValueError(f"{file_name} must not be empty or whitespace-only.")
        if "\x00" in secret:
            raise ValueError(f"{file_name} contains invalid text.")
        return secret


settings = Settings()


def build_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def database_backend(url: str) -> str:
    """Validate and return the explicitly supported async database backend."""

    parsed = make_url(url)
    backend = parsed.get_backend_name()
    driver = parsed.get_driver_name()
    supported_drivers = {
        "sqlite": "aiosqlite",
        "postgresql": "asyncpg",
    }
    if supported_drivers.get(backend) != driver:
        raise ValueError("Unsupported database URL; use sqlite+aiosqlite or postgresql+asyncpg.")
    return backend
