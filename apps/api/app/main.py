from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.routes import router
from app.application.service import AgentService
from app.domain.contracts import EmbeddingProvider, RuntimeMode
from app.evaluation.graders import DeterministicGrader
from app.evaluation.repository import EvaluationRepository
from app.evaluation.service import EvaluationService
from app.evaluation.worker import LocalEvaluationWorker
from app.knowledge.chunking import TextChunker
from app.knowledge.embeddings import DeterministicEmbeddingProvider, OpenAIEmbeddingProvider
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.service import KnowledgeService
from app.knowledge.vector_store import PgVectorStore, SqlAlchemyVectorStore
from app.knowledge.worker import LocalIngestionWorker
from app.memory.keys import normalized_memory_key
from app.memory.policy import MemoryPolicy
from app.memory.retriever import MemoryRetriever
from app.memory.store import SqlAlchemyMemoryStore
from app.persistence.database import build_database, database_backend, settings
from app.persistence.models import Base
from app.persistence.repositories import Repositories
from app.runtime.agents_sdk import AgentsSdkRuntime
from app.runtime.mock import MockRuntime
from app.runtime.providers import DeepSeekProvider, OpenAIProvider
from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.registry import ToolExecutor, default_tool_registry


class SecurityHeadersMiddleware:
    """Add browser hardening headers without BaseHTTPMiddleware task indirection."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(
    database_url: str | None = None, knowledge_storage_path: str | None = None
) -> FastAPI:
    resolved_database_url = database_url or settings.database_url
    backend = database_backend(resolved_database_url)
    engine, sessions = build_database(resolved_database_url)
    embeddings: EmbeddingProvider
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY.")
        embeddings = OpenAIEmbeddingProvider(
            settings.openai_api_key,
            settings.openai_embedding_model,
            timeout_seconds=settings.openai_request_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
    else:
        embeddings = DeterministicEmbeddingProvider()
    knowledge_repository = KnowledgeRepository(sessions)
    vector_store = (
        PgVectorStore(sessions, dimensions=embeddings.dimensions)
        if backend == "postgresql"
        else SqlAlchemyVectorStore(sessions)
    )
    knowledge_service = KnowledgeService(
        knowledge_repository,
        vector_store,
        embeddings,
        Path(knowledge_storage_path or settings.knowledge_storage_path),
        settings.knowledge_max_file_bytes,
        chunker=TextChunker(max_chunks=settings.knowledge_max_chunks),
        max_extracted_chars=settings.knowledge_max_extracted_chars,
        parser_timeout_seconds=settings.knowledge_parser_timeout_seconds,
    )
    worker = LocalIngestionWorker(knowledge_service, settings.knowledge_worker_count)
    knowledge_service.bind_enqueue(worker.enqueue)
    registry = default_tool_registry([KnowledgeSearchTool(knowledge_service).as_tool()])
    executor = ToolExecutor(registry)
    repositories = Repositories(sessions)
    memory_store = SqlAlchemyMemoryStore(sessions)
    memory_policy = MemoryPolicy()
    memory_retriever = MemoryRetriever(memory_store, memory_policy)
    openai_provider = OpenAIProvider(
        api_key=settings.openai_api_key,
        default_model=settings.openai_model,
        tracing_disabled=settings.openai_agents_disable_tracing,
        request_timeout_seconds=settings.openai_request_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_output_tokens=settings.openai_max_output_tokens,
    )
    deepseek_provider = DeepSeekProvider(
        api_key=settings.deepseek_api_key,
        default_model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        request_timeout_seconds=settings.deepseek_request_timeout_seconds,
        max_retries=settings.deepseek_max_retries,
        max_output_tokens=settings.deepseek_max_output_tokens,
    )
    service = AgentService(
        repositories=repositories,
        runtimes={
            RuntimeMode.MOCK: MockRuntime(
                executor, blocking_input=settings.mock_provider_block_input
            ),
            RuntimeMode.OPENAI: AgentsSdkRuntime(openai_provider, executor),
            RuntimeMode.DEEPSEEK: AgentsSdkRuntime(deepseek_provider, executor),
        },
        available_tools=registry.names,
        memory_store=memory_store,
        memory_retriever=memory_retriever,
        memory_policy=memory_policy,
    )
    evaluation_repository = EvaluationRepository(sessions)
    evaluation_service = EvaluationService(
        repository=evaluation_repository,
        repositories=repositories,
        agent_service=service,
        memory_store=memory_store,
        memory_policy=memory_policy,
        grader=DeterministicGrader(),
    )
    evaluation_worker = LocalEvaluationWorker(
        evaluation_service, settings.evaluation_worker_count
    )
    evaluation_service.bind_enqueue(evaluation_worker.enqueue)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker_started = False
        evaluation_worker_started = False
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.run_sync(_apply_lightweight_schema_migrations)
            await vector_store.initialize()
            app.state.agent_service = service
            app.state.knowledge_service = knowledge_service
            app.state.evaluation_service = evaluation_service
            app.state.evaluation_worker = evaluation_worker
            app.state.database_sessions = sessions
            app.state.openai_provider = openai_provider
            app.state.deepseek_provider = deepseek_provider
            app.state.model_providers = {
                openai_provider.name: openai_provider,
                deepseek_provider.name: deepseek_provider,
            }
            app.state.selected_model_provider = settings.llm_provider
            await service.recover_interrupted_runs()
            await worker.start()
            worker_started = True
            await evaluation_worker.start()
            evaluation_worker_started = True
            yield
        finally:
            await service.shutdown()
            if evaluation_worker_started:
                await evaluation_worker.stop()
            if worker_started:
                await worker.stop()
            await embeddings.close()
            await engine.dispose()

    app = FastAPI(title="Agent Studio API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
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
    if "kind" not in agent_columns:
        connection.execute(
            text("ALTER TABLE agents ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'normal'")
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_kind ON agents (kind)"))
    if "source_agent_id" not in agent_columns:
        connection.execute(text("ALTER TABLE agents ADD COLUMN source_agent_id VARCHAR(36)"))

    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    if "run_kind" not in run_columns:
        connection.execute(
            text("ALTER TABLE runs ADD COLUMN run_kind VARCHAR(20) NOT NULL DEFAULT 'normal'")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_runs_run_kind ON runs (run_kind)")
        )

    knowledge_base_columns = {
        column["name"] for column in inspector.get_columns("knowledge_bases")
    }
    if "embedding_dimensions" not in knowledge_base_columns:
        connection.execute(
            text("ALTER TABLE knowledge_bases ADD COLUMN embedding_dimensions INTEGER")
        )
        connection.execute(
            text(
                "UPDATE knowledge_bases SET embedding_dimensions = "
                "CASE WHEN embedding_provider = 'openai' THEN 1536 ELSE 256 END"
            )
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

    connection.execute(
        text(
            """
            INSERT INTO agent_memory_settings (agent_id, enabled)
            SELECT agents.id, true
            FROM agents
            WHERE NOT EXISTS (
                SELECT 1
                FROM agent_memory_settings
                WHERE agent_memory_settings.agent_id = agents.id
            )
            """
        )
    )

    memory_columns = {column["name"] for column in inspector.get_columns("memories")}
    if "normalized_key" not in memory_columns:
        connection.execute(text("ALTER TABLE memories ADD COLUMN normalized_key VARCHAR(64)"))
        rows = connection.execute(
            text("SELECT id, agent_id, content FROM memories ORDER BY created_at DESC, id DESC")
        ).mappings()
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = normalized_memory_key(str(row["content"]))
            scoped_key = (str(row["agent_id"]), key)
            if scoped_key in seen:
                connection.execute(
                    text("DELETE FROM memories WHERE id = :id"), {"id": row["id"]}
                )
                continue
            seen.add(scoped_key)
            connection.execute(
                text("UPDATE memories SET normalized_key = :key WHERE id = :id"),
                {"key": key, "id": row["id"]},
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_agent_normalized_key "
                "ON memories (agent_id, normalized_key)"
            )
        )
