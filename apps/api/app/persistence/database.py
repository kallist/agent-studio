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


settings = Settings()


def build_database(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
