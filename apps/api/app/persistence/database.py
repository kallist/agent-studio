from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./agent_studio.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"
    openai_agents_disable_tracing: bool = True
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

    @field_validator("cors_origins", "allowed_hosts")
    @classmethod
    def reject_unbounded_network_lists(cls, value: str) -> str:
        entries = [entry.strip() for entry in value.split(",") if entry.strip()]
        if not entries or "*" in entries:
            raise ValueError("Network origin and host lists must be explicit and non-empty.")
        return ",".join(entries)


settings = Settings()


def build_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
