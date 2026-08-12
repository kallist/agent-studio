from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.application.service import AgentService
from app.domain.contracts import RuntimeMode
from app.persistence.database import build_database, settings
from app.persistence.models import Base
from app.persistence.repositories import Repositories
from app.runtime.agents_sdk import AgentsSdkRuntime
from app.runtime.mock import MockRuntime
from app.runtime.providers import OpenAIProvider
from app.tools.registry import ToolExecutor, default_tool_registry


def create_app(database_url: str | None = None) -> FastAPI:
    engine, sessions = build_database(database_url or settings.database_url)
    registry = default_tool_registry()
    executor = ToolExecutor(registry)
    repositories = Repositories(sessions)
    provider = OpenAIProvider(
        api_key=settings.openai_api_key,
        default_model=settings.openai_model,
        tracing_disabled=settings.openai_agents_disable_tracing,
    )
    service = AgentService(
        repositories=repositories,
        runtimes={
            RuntimeMode.MOCK: MockRuntime(executor),
            RuntimeMode.OPENAI: AgentsSdkRuntime(provider, executor),
        },
        available_tools=registry.names,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        app.state.agent_service = service
        yield
        await engine.dispose()

    app = FastAPI(title="Agent Studio API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
