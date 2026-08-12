from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.persistence.database import settings


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    database_path = (tmp_path / "test.db").as_posix()
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{database_path}",
        knowledge_storage_path=str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
