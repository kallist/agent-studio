from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.main import create_app
from app.persistence.database import build_database, settings
from app.persistence.models import Base

DESTRUCTIVE_RESET_CONFIRMATION = "I_UNDERSTAND_THIS_DROPS_TEST_TABLES"


def _guard_test_database_url(raw_url: str) -> str:
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.get_driver_name() != "asyncpg":
        raise RuntimeError("POSTGRES_TEST_DATABASE_URL must use the postgresql+asyncpg driver.")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("PostgreSQL integration tests only accept a loopback database host.")
    if not url.database or not url.database.endswith("_test"):
        raise RuntimeError("PostgreSQL integration tests require a database ending in '_test'.")
    if not url.username or not url.username.endswith("_test"):
        raise RuntimeError("PostgreSQL integration tests require a role ending in '_test'.")
    return raw_url


@pytest.fixture
def postgres_database_url() -> str:
    raw_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured.")
    return _guard_test_database_url(raw_url)


@pytest.fixture
def postgres_no_vector_database_url() -> str:
    raw_url = os.getenv("POSTGRES_NO_VECTOR_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("POSTGRES_NO_VECTOR_TEST_DATABASE_URL is not configured.")
    return _guard_test_database_url(raw_url)


async def _reset_test_schema(database_url: str) -> None:
    """Reset only a guarded, loopback, disposable *_test database."""

    if os.getenv("POSTGRES_TEST_ALLOW_DESTRUCTIVE_RESET") != DESTRUCTIVE_RESET_CONFIRMATION:
        raise RuntimeError(
            "Set POSTGRES_TEST_ALLOW_DESTRUCTIVE_RESET to the documented confirmation "
            "before resetting PostgreSQL test tables."
        )
    guarded_url = _guard_test_database_url(database_url)
    expected_database = make_url(guarded_url).database
    engine, _ = build_database(guarded_url)
    try:
        async with engine.begin() as connection:
            actual_database = await connection.scalar(text("SELECT current_database()"))
            actual_user = await connection.scalar(text("SELECT current_user"))
            if actual_database != expected_database or not str(actual_database).endswith("_test"):
                raise RuntimeError("Refusing to reset an unexpected PostgreSQL database.")
            if not str(actual_user).endswith("_test"):
                raise RuntimeError("Refusing to reset PostgreSQL through a non-test role.")
            await connection.execute(text("DROP TABLE IF EXISTS rag_vectors CASCADE"))
            await connection.run_sync(Base.metadata.drop_all)
    finally:
        await engine.dispose()


@pytest.fixture
async def postgres_app(
    postgres_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    await _reset_test_schema(postgres_database_url)
    real_openai_enabled = os.getenv("RUN_REAL_OPENAI_TESTS") == "1"
    real_deepseek_enabled = os.getenv("RUN_REAL_DEEPSEEK_TESTS") == "1"
    monkeypatch.setattr(
        settings,
        "openai_api_key",
        os.getenv("OPENAI_API_KEY") if real_openai_enabled else None,
    )
    if real_openai_enabled:
        monkeypatch.setattr(settings, "openai_max_output_tokens", 128)
        monkeypatch.setattr(settings, "openai_max_retries", 1)
        monkeypatch.setattr(settings, "openai_request_timeout_seconds", 30)
    monkeypatch.setattr(
        settings,
        "deepseek_api_key",
        os.getenv("DEEPSEEK_API_KEY") if real_deepseek_enabled else None,
    )
    if real_deepseek_enabled:
        monkeypatch.setattr(settings, "deepseek_max_output_tokens", 128)
        monkeypatch.setattr(settings, "deepseek_max_retries", 1)
        monkeypatch.setattr(settings, "deepseek_request_timeout_seconds", 30)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    app = create_app(
        postgres_database_url,
        knowledge_storage_path=str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def postgres_client(postgres_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=postgres_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
