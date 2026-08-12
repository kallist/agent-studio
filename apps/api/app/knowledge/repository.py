from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import (
    DocumentView,
    IngestionJobView,
    IngestionState,
    KnowledgeBaseCreate,
    KnowledgeBaseView,
    KnowledgeCitation,
    RetrievalFilters,
    VectorMatch,
)
from app.domain.errors import EntityNotFoundError
from app.knowledge.chunking import ChunkDraft
from app.persistence.models import (
    ChunkModel,
    DocumentModel,
    IngestionJobModel,
    KnowledgeBaseModel,
)


@dataclass(frozen=True)
class StoredDocument:
    id: UUID
    knowledge_base_id: UUID
    filename: str
    source: str
    mime_type: str
    storage_path: Path


@dataclass(frozen=True)
class StoredChunk:
    id: UUID
    content: str
    metadata: dict[str, object]


class KnowledgeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_base(
        self,
        request: KnowledgeBaseCreate,
        embedding_provider: str,
        embedding_model: str,
    ) -> KnowledgeBaseView:
        async with self._sessions() as session:
            model = KnowledgeBaseModel(
                name=request.name.strip(),
                description=request.description.strip(),
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _base_view(model, 0)

    async def list_bases(self) -> list[KnowledgeBaseView]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(KnowledgeBaseModel, func.count(DocumentModel.id))
                    .outerjoin(DocumentModel)
                    .group_by(KnowledgeBaseModel.id)
                    .order_by(KnowledgeBaseModel.created_at.desc())
                )
            ).all()
            return [_base_view(model, count) for model, count in rows]

    async def get_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(KnowledgeBaseModel, func.count(DocumentModel.id))
                    .outerjoin(DocumentModel)
                    .where(KnowledgeBaseModel.id == str(knowledge_base_id))
                    .group_by(KnowledgeBaseModel.id)
                )
            ).one_or_none()
            if row is None:
                raise EntityNotFoundError(f"Knowledge base '{knowledge_base_id}' was not found.")
            return _base_view(row[0], row[1])

    async def create_document_and_job(
        self,
        knowledge_base_id: UUID,
        filename: str,
        source: str,
        mime_type: str,
        size_bytes: int,
        storage_path: Path,
    ) -> tuple[DocumentView, IngestionJobView]:
        await self.get_base(knowledge_base_id)
        async with self._sessions() as session:
            document = DocumentModel(
                knowledge_base_id=str(knowledge_base_id),
                filename=filename,
                source=source,
                mime_type=mime_type,
                size_bytes=size_bytes,
                storage_path=str(storage_path),
            )
            job = IngestionJobModel(document=document, state=IngestionState.QUEUED.value)
            session.add_all([document, job])
            await session.commit()
            await session.refresh(document)
            await session.refresh(job)
            job_view = _job_view(job)
            return _document_view(document, job_view), job_view

    async def list_documents(self, knowledge_base_id: UUID) -> list[DocumentView]:
        await self.get_base(knowledge_base_id)
        async with self._sessions() as session:
            documents = list(
                await session.scalars(
                    select(DocumentModel)
                    .where(DocumentModel.knowledge_base_id == str(knowledge_base_id))
                    .order_by(DocumentModel.created_at.desc())
                )
            )
            views: list[DocumentView] = []
            for document in documents:
                job = await session.scalar(
                    select(IngestionJobModel)
                    .where(IngestionJobModel.document_id == document.id)
                    .order_by(IngestionJobModel.queued_at.desc())
                    .limit(1)
                )
                views.append(_document_view(document, _job_view(job) if job else None))
            return views

    async def get_job(self, job_id: UUID) -> IngestionJobView:
        async with self._sessions() as session:
            model = await session.get(IngestionJobModel, str(job_id))
            if model is None:
                raise EntityNotFoundError(f"Ingestion job '{job_id}' was not found.")
            return _job_view(model)

    async def recover_jobs(self) -> list[UUID]:
        async with self._sessions() as session:
            await session.execute(
                update(IngestionJobModel)
                .where(IngestionJobModel.state == IngestionState.PROCESSING.value)
                .values(state=IngestionState.QUEUED.value, started_at=None)
            )
            rows = await session.scalars(
                select(IngestionJobModel.id)
                .where(IngestionJobModel.state == IngestionState.QUEUED.value)
                .order_by(IngestionJobModel.queued_at)
            )
            await session.commit()
            return [UUID(value) for value in rows]

    async def mark_processing(self, job_id: UUID) -> StoredDocument:
        async with self._sessions() as session:
            job = await session.get(IngestionJobModel, str(job_id))
            if job is None:
                raise EntityNotFoundError(f"Ingestion job '{job_id}' was not found.")
            document = await session.get(DocumentModel, job.document_id)
            if document is None:
                raise EntityNotFoundError(f"Document '{job.document_id}' was not found.")
            job.state = IngestionState.PROCESSING.value
            job.started_at = datetime.now(UTC)
            job.completed_at = None
            job.error = None
            await session.commit()
            return _stored_document(document)

    async def finish_job(
        self, job_id: UUID, state: IngestionState, error: str | None = None
    ) -> None:
        if state not in {IngestionState.COMPLETED, IngestionState.FAILED}:
            raise ValueError("Ingestion jobs can only finish as completed or failed.")
        async with self._sessions() as session:
            job = await session.get(IngestionJobModel, str(job_id))
            if job is None:
                raise EntityNotFoundError(f"Ingestion job '{job_id}' was not found.")
            job.state = state.value
            job.error = error
            job.completed_at = datetime.now(UTC)
            await session.commit()

    async def replace_chunks(
        self, document: StoredDocument, drafts: list[ChunkDraft]
    ) -> list[StoredChunk]:
        async with self._sessions() as session:
            await session.execute(
                delete(ChunkModel).where(ChunkModel.document_id == str(document.id))
            )
            models = [
                ChunkModel(
                    knowledge_base_id=str(document.knowledge_base_id),
                    document_id=str(document.id),
                    chunk_index=draft.index,
                    content=draft.content,
                    token_count=draft.token_count,
                    metadata_json=json.dumps(draft.metadata, ensure_ascii=False),
                )
                for draft in drafts
            ]
            session.add_all(models)
            await session.commit()
            for model in models:
                await session.refresh(model)
            return [
                StoredChunk(
                    id=UUID(model.id),
                    content=model.content,
                    metadata=json.loads(model.metadata_json),
                )
                for model in models
            ]

    async def list_chunk_candidates(
        self, knowledge_base_ids: list[UUID], filters: RetrievalFilters | None
    ) -> list[tuple[UUID, str]]:
        if not knowledge_base_ids:
            return []
        statement = (
            select(ChunkModel.id, ChunkModel.content)
            .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
            .where(ChunkModel.knowledge_base_id.in_([str(value) for value in knowledge_base_ids]))
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
        return [(UUID(chunk_id), content) for chunk_id, content in rows]

    async def hydrate_matches(self, matches: list[VectorMatch]) -> list[KnowledgeCitation]:
        if not matches:
            return []
        ids = [str(item.chunk_id) for item in matches]
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ChunkModel, DocumentModel)
                    .join(DocumentModel, DocumentModel.id == ChunkModel.document_id)
                    .where(ChunkModel.id.in_(ids))
                )
            ).all()
        by_id = {chunk.id: (chunk, document) for chunk, document in rows}
        citations: list[KnowledgeCitation] = []
        for match in matches:
            row = by_id.get(str(match.chunk_id))
            if row is None:
                continue
            chunk, document = row
            citations.append(
                KnowledgeCitation(
                    document_id=UUID(document.id),
                    document=document.filename,
                    chunk_id=UUID(chunk.id),
                    chunk_index=chunk.chunk_index,
                    source=document.source,
                    score=round(match.score, 6),
                    content=chunk.content,
                    metadata=json.loads(chunk.metadata_json),
                )
            )
        return citations


def _base_view(model: KnowledgeBaseModel, document_count: int) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=UUID(model.id),
        name=model.name,
        description=model.description,
        embedding_provider=model.embedding_provider,
        embedding_model=model.embedding_model,
        created_at=_aware(model.created_at),
        document_count=document_count,
    )


def _job_view(model: IngestionJobModel) -> IngestionJobView:
    return IngestionJobView(
        id=UUID(model.id),
        document_id=UUID(model.document_id),
        state=IngestionState(model.state),
        error=model.error,
        queued_at=_aware(model.queued_at),
        started_at=_aware(model.started_at) if model.started_at else None,
        completed_at=_aware(model.completed_at) if model.completed_at else None,
    )


def _document_view(model: DocumentModel, job: IngestionJobView | None) -> DocumentView:
    return DocumentView(
        id=UUID(model.id),
        knowledge_base_id=UUID(model.knowledge_base_id),
        filename=model.filename,
        source=model.source,
        mime_type=model.mime_type,
        size_bytes=model.size_bytes,
        created_at=_aware(model.created_at),
        ingestion=job,
    )


def _stored_document(model: DocumentModel) -> StoredDocument:
    return StoredDocument(
        id=UUID(model.id),
        knowledge_base_id=UUID(model.knowledge_base_id),
        filename=model.filename,
        source=model.source,
        mime_type=model.mime_type,
        storage_path=Path(model.storage_path),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
