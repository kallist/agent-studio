from __future__ import annotations

import json
import math
from uuid import UUID

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import TextClause

from app.domain.contracts import EmbeddingVector, IngestionState, RetrievalFilters, VectorMatch
from app.domain.errors import KnowledgeValidationError
from app.persistence.models import (
    ChunkModel,
    DocumentModel,
    EmbeddingModel,
    IngestionJobModel,
)


class SqlAlchemyVectorStore:
    """Portable fallback that persists vectors and computes cosine similarity in-process."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def initialize(self) -> None:
        return None

    async def upsert(self, records: list[EmbeddingVector]) -> None:
        if not records:
            return
        chunk_ids = [str(record.chunk_id) for record in records]
        async with self._sessions() as session:
            await session.execute(
                delete(EmbeddingModel).where(EmbeddingModel.chunk_id.in_(chunk_ids))
            )
            session.add_all(
                [
                    EmbeddingModel(
                        chunk_id=str(record.chunk_id),
                        provider=record.provider,
                        model=record.model,
                        dimensions=len(record.vector),
                        vector_json=json.dumps(record.vector),
                        metadata_json=json.dumps(record.metadata, ensure_ascii=False),
                    )
                    for record in records
                ]
            )
            await session.commit()

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        if not chunk_ids:
            return
        async with self._sessions() as session:
            await session.execute(
                delete(EmbeddingModel).where(
                    EmbeddingModel.chunk_id.in_([str(value) for value in chunk_ids])
                )
            )
            await session.commit()

    async def delete_document(self, document_id: UUID) -> None:
        async with self._sessions() as session:
            chunk_ids = select(ChunkModel.id).where(ChunkModel.document_id == str(document_id))
            await session.execute(
                delete(EmbeddingModel).where(EmbeddingModel.chunk_id.in_(chunk_ids))
            )
            await session.commit()

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[VectorMatch]:
        if not knowledge_base_ids:
            return []
        statement = (
            select(EmbeddingModel.chunk_id, EmbeddingModel.vector_json)
            .join(ChunkModel, ChunkModel.id == EmbeddingModel.chunk_id)
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .join(IngestionJobModel, IngestionJobModel.id == ChunkModel.ingestion_job_id)
            .where(ChunkModel.knowledge_base_id.in_([str(value) for value in knowledge_base_ids]))
            .where(IngestionJobModel.state == IngestionState.COMPLETED.value)
            .where(IngestionJobModel.document_id == ChunkModel.document_id)
        )
        if filters is not None:
            if filters.document_id is not None:
                statement = statement.where(DocumentModel.id == str(filters.document_id))
            if filters.source is not None:
                statement = statement.where(DocumentModel.source == filters.source)
            if filters.filename is not None:
                statement = statement.where(DocumentModel.filename == filters.filename)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        matches = [
            VectorMatch(
                chunk_id=UUID(chunk_id),
                score=_cosine(query_vector, json.loads(vector_json)),
            )
            for chunk_id, vector_json in rows
            if vector_json is not None
        ]
        return sorted(matches, key=lambda item: item.score, reverse=True)[:top_k]


class PgVectorStore(SqlAlchemyVectorStore):
    """PostgreSQL adapter using pgvector for server-side cosine search."""

    _MAX_INDEXED_DIMENSIONS = 2_000

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        dimensions: int,
    ) -> None:
        super().__init__(sessions)
        if not 1 <= dimensions <= self._MAX_INDEXED_DIMENSIONS:
            raise ValueError(
                "PgVectorStore dimensions must be between 1 and 2000 for the HNSW vector index."
            )
        self._dimensions = dimensions

    async def initialize(self) -> None:
        vector_type = f"vector({self._dimensions})"
        try:
            async with self._sessions() as session, session.begin():
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS rag_vectors (
                            chunk_id varchar(36) PRIMARY KEY
                                REFERENCES chunks(id) ON DELETE CASCADE,
                            embedding {vector_type} NOT NULL
                        )
                        """
                    )
                )
                stored_type = await session.scalar(
                    text(
                        """
                        SELECT format_type(attribute.atttypid, attribute.atttypmod)
                        FROM pg_attribute AS attribute
                        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                        WHERE relation.relname = 'rag_vectors'
                          AND attribute.attname = 'embedding'
                          AND attribute.attnum > 0
                        """
                    )
                )
                if stored_type != vector_type:
                    await session.execute(
                        text(
                            "ALTER TABLE rag_vectors "
                            f"ALTER COLUMN embedding TYPE {vector_type} "
                            f"USING embedding::{vector_type}"
                        )
                    )
                await session.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_rag_vectors_embedding_hnsw
                        ON rag_vectors USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                )
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "PostgreSQL pgvector initialization failed. Ensure the database is reachable "
                "and the configured role can create and use the vector extension."
            ) from exc

    async def upsert(self, records: list[EmbeddingVector]) -> None:
        if not records:
            return
        self._validate_records(records)
        chunk_ids = [str(record.chunk_id) for record in records]
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(EmbeddingModel).where(EmbeddingModel.chunk_id.in_(chunk_ids))
            )
            session.add_all(
                [
                    EmbeddingModel(
                        chunk_id=str(record.chunk_id),
                        provider=record.provider,
                        model=record.model,
                        dimensions=self._dimensions,
                        vector_json=None,
                        metadata_json=json.dumps(record.metadata, ensure_ascii=False),
                    )
                    for record in records
                ]
            )
            await session.flush()
            for record in records:
                await session.execute(
                    text(
                        """
                        INSERT INTO rag_vectors (chunk_id, embedding)
                        VALUES (:chunk_id, CAST(:embedding AS vector))
                        ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "chunk_id": str(record.chunk_id),
                        "embedding": _vector_literal(record.vector),
                    },
                )

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        if not chunk_ids:
            return
        serialized_ids = [str(value) for value in chunk_ids]
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM rag_vectors WHERE chunk_id IN :chunk_ids").bindparams(
                    bindparam("chunk_ids", expanding=True)
                ),
                {"chunk_ids": serialized_ids},
            )
            await session.execute(
                delete(EmbeddingModel).where(EmbeddingModel.chunk_id.in_(serialized_ids))
            )

    async def delete_document(self, document_id: UUID) -> None:
        chunk_ids = select(ChunkModel.id).where(ChunkModel.document_id == str(document_id))
        async with self._sessions() as session, session.begin():
            serialized_ids = list(await session.scalars(chunk_ids))
            if serialized_ids:
                await session.execute(
                    text("DELETE FROM rag_vectors WHERE chunk_id IN :chunk_ids").bindparams(
                        bindparam("chunk_ids", expanding=True)
                    ),
                    {"chunk_ids": serialized_ids},
                )
            await session.execute(
                delete(EmbeddingModel).where(EmbeddingModel.chunk_id.in_(chunk_ids))
            )

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[VectorMatch]:
        if not knowledge_base_ids:
            return []
        self._validate_vector(query_vector)
        statement, params = self._build_search_query(
            knowledge_base_ids, query_vector, top_k, filters
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement, params)).all()
        return [
            VectorMatch(chunk_id=UUID(chunk_id), score=float(score)) for chunk_id, score in rows
        ]

    def _validate_records(self, records: list[EmbeddingVector]) -> None:
        for record in records:
            self._validate_vector(record.vector)

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self._dimensions:
            raise KnowledgeValidationError(
                f"PostgreSQL vector storage requires exactly {self._dimensions} dimensions; "
                f"received {len(vector)}."
            )
        if not all(math.isfinite(value) for value in vector):
            raise KnowledgeValidationError("Embedding vectors must contain only finite numbers.")

    @staticmethod
    def _build_search_query(
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None,
    ) -> tuple[TextClause, dict[str, object]]:
        clauses = [
            "c.knowledge_base_id IN :knowledge_base_ids",
            "j.state = :completed_state",
            "j.document_id = c.document_id",
        ]
        params: dict[str, object] = {
            "knowledge_base_ids": [str(value) for value in knowledge_base_ids],
            "query_vector": _vector_literal(query_vector),
            "top_k": top_k,
            "completed_state": IngestionState.COMPLETED.value,
        }
        if filters is not None:
            if filters.document_id is not None:
                clauses.append("d.id = :document_id")
                params["document_id"] = str(filters.document_id)
            if filters.source is not None:
                clauses.append("d.source = :source")
                params["source"] = filters.source
            if filters.filename is not None:
                clauses.append("d.filename = :filename")
                params["filename"] = filters.filename
        statement = text(
            f"""
            SELECT v.chunk_id,
                   1 - (v.embedding <=> CAST(:query_vector AS vector)) AS score
            FROM rag_vectors v
            JOIN chunks c ON c.id = v.chunk_id
            JOIN documents d ON d.id = c.document_id
            JOIN ingestion_jobs j ON j.id = c.ingestion_job_id
            WHERE {" AND ".join(clauses)}
            ORDER BY v.embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k
            """
        ).bindparams(bindparam("knowledge_base_ids", expanding=True))
        return statement, params


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in vector) + "]"
