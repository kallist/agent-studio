from __future__ import annotations

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
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    knowledge_storage_path: str = "./data/knowledge"
    knowledge_max_file_bytes: int = 10 * 1024 * 1024
    knowledge_worker_count: int = 1
    embedding_provider: str = "local"
    openai_embedding_model: str = "text-embedding-3-small"


settings = Settings()


def build_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
