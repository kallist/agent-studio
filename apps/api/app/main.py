from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.api.routes import router
from app.application.service import AgentService
from app.domain.contracts import EmbeddingProvider, RuntimeMode
from app.knowledge.embeddings import DeterministicEmbeddingProvider, OpenAIEmbeddingProvider
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.service import KnowledgeService
from app.knowledge.vector_store import PgVectorStore, SqlAlchemyVectorStore
from app.knowledge.worker import LocalIngestionWorker
from app.memory.policy import MemoryPolicy
from app.memory.retriever import MemoryRetriever
from app.memory.store import SqlAlchemyMemoryStore
from app.persistence.database import build_database, settings
from app.persistence.models import Base
from app.persistence.repositories import Repositories
from app.runtime.agents_sdk import AgentsSdkRuntime
from app.runtime.mock import MockRuntime
from app.runtime.providers import OpenAIProvider
from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.registry import ToolExecutor, default_tool_registry


def create_app(
    database_url: str | None = None, knowledge_storage_path: str | None = None
) -> FastAPI:
    resolved_database_url = database_url or settings.database_url
    engine, sessions = build_database(resolved_database_url)
    embeddings: EmbeddingProvider
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        embeddings = OpenAIEmbeddingProvider(
            settings.openai_api_key, settings.openai_embedding_model
        )
    else:
        embeddings = DeterministicEmbeddingProvider()
    knowledge_repository = KnowledgeRepository(sessions)
    vector_store = (
        PgVectorStore(sessions)
        if resolved_database_url.startswith("postgresql")
        else SqlAlchemyVectorStore(sessions)
    )
    knowledge_service = KnowledgeService(
        knowledge_repository,
        vector_store,
        embeddings,
        Path(knowledge_storage_path or settings.knowledge_storage_path),
        settings.knowledge_max_file_bytes,
    )
    worker = LocalIngestionWorker(knowledge_service, settings.knowledge_worker_count)
    knowledge_service.bind_enqueue(worker.enqueue)
    registry = default_tool_registry([KnowledgeSearchTool(knowledge_service).as_tool()])
    executor = ToolExecutor(registry)
    repositories = Repositories(sessions)
    memory_store = SqlAlchemyMemoryStore(sessions)
    memory_policy = MemoryPolicy()
    memory_retriever = MemoryRetriever(memory_store, memory_policy)
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
        memory_store=memory_store,
        memory_retriever=memory_retriever,
        memory_policy=memory_policy,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_apply_lightweight_schema_migrations)
        await vector_store.initialize()
        app.state.agent_service = service
        app.state.knowledge_service = knowledge_service
        await worker.start()
        yield
        await worker.stop()
        await engine.dispose()

    app = FastAPI(title="Agent Studio API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()


def _apply_lightweight_schema_migrations(connection: Connection) -> None:
    """Bridge the pre-Alembic local schema until the first formal migration baseline."""
    inspector = inspect(connection)
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    if "knowledge_base_ids_json" not in agent_columns:
        connection.execute(
            text("ALTER TABLE agents ADD COLUMN knowledge_base_ids_json TEXT DEFAULT '[]'")
        )

    chunk_columns = {column["name"] for column in inspector.get_columns("chunks")}
    if "ingestion_job_id" not in chunk_columns:
        connection.execute(text("ALTER TABLE chunks ADD COLUMN ingestion_job_id VARCHAR(36)"))
        # Legacy chunks are safe to expose only when the newest job for their
        # document is completed. Ambiguous processing/failed replacements stay hidden.
        connection.execute(
            text(
                """
                UPDATE chunks
                SET ingestion_job_id = (
                    SELECT ingestion_jobs.id
                    FROM ingestion_jobs
                    WHERE ingestion_jobs.document_id = chunks.document_id
                    ORDER BY ingestion_jobs.queued_at DESC, ingestion_jobs.id DESC
                    LIMIT 1
                )
                WHERE (
                    SELECT ingestion_jobs.state
                    FROM ingestion_jobs
                    WHERE ingestion_jobs.document_id = chunks.document_id
                    ORDER BY ingestion_jobs.queued_at DESC, ingestion_jobs.id DESC
                    LIMIT 1
                ) = 'completed'
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_ingestion_job_id ON chunks (ingestion_job_id)"
            )
        )
