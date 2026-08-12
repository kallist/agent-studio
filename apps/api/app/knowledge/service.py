from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from app.domain.contracts import (
    DocumentUploadAccepted,
    DocumentView,
    EmbeddingProvider,
    EmbeddingVector,
    IngestionJobView,
    IngestionState,
    KnowledgeBaseCreate,
    KnowledgeBaseView,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RetrievalFilters,
    VectorMatch,
    VectorStore,
)
from app.domain.errors import DocumentParsingError, KnowledgeValidationError
from app.knowledge.chunking import TextChunker
from app.knowledge.parsers import parser_for
from app.knowledge.repository import KnowledgeRepository

_ALLOWED_TYPES: dict[str, tuple[str, set[str]]] = {
    ".txt": ("text/plain", {"text/plain", "application/octet-stream"}),
    ".md": (
        "text/markdown",
        {"text/markdown", "text/plain", "text/x-markdown", "application/octet-stream"},
    ),
    ".pdf": ("application/pdf", {"application/pdf", "application/octet-stream"}),
}


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        vector_store: VectorStore,
        embeddings: EmbeddingProvider,
        storage_root: Path,
        max_file_bytes: int,
        chunker: TextChunker | None = None,
    ) -> None:
        self._repository = repository
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._storage_root = storage_root.resolve()
        self._max_file_bytes = max_file_bytes
        self._chunker = chunker or TextChunker()
        self._enqueue: Callable[[UUID], None] | None = None

    def bind_enqueue(self, enqueue: Callable[[UUID], None]) -> None:
        self._enqueue = enqueue

    async def create_base(self, request: KnowledgeBaseCreate) -> KnowledgeBaseView:
        return await self._repository.create_base(
            request, self._embeddings.name, self._embeddings.model
        )

    async def list_bases(self) -> list[KnowledgeBaseView]:
        return await self._repository.list_bases()

    async def get_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView:
        return await self._repository.get_base(knowledge_base_id)

    async def list_documents(self, knowledge_base_id: UUID) -> list[DocumentView]:
        return await self._repository.list_documents(knowledge_base_id)

    async def get_job(self, job_id: UUID) -> IngestionJobView:
        return await self._repository.get_job(job_id)

    async def queue_upload(
        self,
        knowledge_base_id: UUID,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> DocumentUploadAccepted:
        safe_name, mime_type, suffix = _validate_upload(
            filename, content_type, data, self._max_file_bytes
        )
        self._storage_root.mkdir(parents=True, exist_ok=True)
        storage_path = (self._storage_root / f"{uuid4()}{suffix}").resolve()
        if self._storage_root not in storage_path.parents:
            raise KnowledgeValidationError("Upload path escaped the configured storage root.")
        await asyncio.to_thread(storage_path.write_bytes, data)
        try:
            document, job = await self._repository.create_document_and_job(
                knowledge_base_id=knowledge_base_id,
                filename=safe_name,
                source=f"upload://{safe_name}",
                mime_type=mime_type,
                size_bytes=len(data),
                storage_path=storage_path,
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise
        if self._enqueue is None:
            await self._repository.finish_job(
                job.id, IngestionState.FAILED, "Ingestion worker is not available."
            )
        else:
            self._enqueue(job.id)
        return DocumentUploadAccepted(document=document, ingestion_job=job)

    async def recover_jobs(self) -> list[UUID]:
        return await self._repository.recover_jobs()

    async def process_job(self, job_id: UUID) -> None:
        try:
            document = await self._repository.mark_processing(job_id)
            parser = parser_for(document.mime_type)
            sections = await asyncio.to_thread(parser.parse, document.storage_path)
            drafts = self._chunker.chunk(sections)
            if not drafts:
                raise DocumentParsingError("Document does not contain searchable text.")
            vectors = await self._embeddings.embed([draft.content for draft in drafts])
            if len(vectors) != len(drafts):
                raise RuntimeError("Embedding provider returned an unexpected vector count.")
            stored_chunks = await self._repository.replace_chunks(document, drafts)
            await self._vector_store.upsert(
                [
                    EmbeddingVector(
                        chunk_id=chunk.id,
                        vector=vector,
                        provider=self._embeddings.name,
                        model=self._embeddings.model,
                        metadata=chunk.metadata,
                    )
                    for chunk, vector in zip(stored_chunks, vectors, strict=True)
                ]
            )
        except DocumentParsingError as exc:
            await self._repository.finish_job(job_id, IngestionState.FAILED, str(exc)[:1_000])
        except Exception:
            await self._repository.finish_job(
                job_id,
                IngestionState.FAILED,
                "Ingestion failed unexpectedly. Check server logs for parser or embedding errors.",
            )
            raise
        else:
            await self._repository.finish_job(job_id, IngestionState.COMPLETED)

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchResponse:
        for knowledge_base_id in knowledge_base_ids:
            base = await self._repository.get_base(knowledge_base_id)
            if (
                base.embedding_provider != self._embeddings.name
                or base.embedding_model != self._embeddings.model
            ):
                raise KnowledgeValidationError(
                    f"Knowledge base '{base.name}' requires re-ingestion with the "
                    "active embedding model."
                )
        query_vector = (await self._embeddings.embed([request.query]))[0]
        semantic = await self._vector_store.search(
            knowledge_base_ids,
            query_vector,
            max(request.top_k * 4, request.top_k),
            request.filters,
        )
        if request.hybrid:
            matches = await self._hybrid_rank(
                knowledge_base_ids, request.query, semantic, request.top_k, request.filters
            )
            algorithm: Literal["semantic", "hybrid"] = "hybrid"
        else:
            matches = semantic[: request.top_k]
            algorithm = "semantic"
        return KnowledgeSearchResponse(
            query=request.query,
            algorithm=algorithm,
            results=await self._repository.hydrate_matches(matches),
        )

    async def _hybrid_rank(
        self,
        knowledge_base_ids: list[UUID],
        query: str,
        semantic: list[VectorMatch],
        top_k: int,
        filters: RetrievalFilters | None,
    ) -> list[VectorMatch]:
        semantic_scores = {item.chunk_id: max(0.0, item.score) for item in semantic}
        lexical_scores = {
            chunk_id: _lexical_score(query, content)
            for chunk_id, content in await self._repository.list_chunk_candidates(
                knowledge_base_ids, filters
            )
        }
        all_ids = semantic_scores.keys() | lexical_scores.keys()
        combined = [
            VectorMatch(
                chunk_id=chunk_id,
                score=0.82 * semantic_scores.get(chunk_id, 0.0)
                + 0.18 * lexical_scores.get(chunk_id, 0.0),
            )
            for chunk_id in all_ids
        ]
        return sorted(combined, key=lambda item: item.score, reverse=True)[:top_k]


def _validate_upload(
    filename: str,
    content_type: str | None,
    data: bytes,
    max_file_bytes: int,
) -> tuple[str, str, str]:
    normalized = unicodedata.normalize("NFC", filename).strip()
    if (
        not normalized
        or len(normalized) > 255
        or Path(normalized).name != normalized
        or "/" in normalized
        or "\\" in normalized
        or any(ord(char) < 32 for char in normalized)
    ):
        raise KnowledgeValidationError("Filename is invalid or contains a path.")
    suffix = Path(normalized).suffix.lower()
    if suffix not in _ALLOWED_TYPES:
        raise KnowledgeValidationError(
            "Unsupported file type. Allowed extensions: .txt, .md, .pdf."
        )
    if not data:
        raise KnowledgeValidationError("Uploaded file is empty.")
    if len(data) > max_file_bytes:
        raise KnowledgeValidationError(
            f"Uploaded file exceeds the {max_file_bytes} byte size limit."
        )
    canonical, accepted = _ALLOWED_TYPES[suffix]
    received = (content_type or "application/octet-stream").split(";", 1)[0].lower().strip()
    if received not in accepted:
        raise KnowledgeValidationError(
            f"MIME type '{received}' does not match the '{suffix}' extension."
        )
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise KnowledgeValidationError("PDF signature is missing or invalid.")
    if suffix != ".pdf":
        if b"\x00" in data[:8_192]:
            raise KnowledgeValidationError("Text upload contains binary data.")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeValidationError("Text uploads must use UTF-8 encoding.") from exc
    return normalized, canonical, suffix


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", text.lower()))
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
    words.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return words


def _lexical_score(query: str, content: str) -> float:
    query_terms = _terms(query)
    content_terms = _terms(content)
    if not query_terms or not content_terms:
        return 0.0
    overlap = len(query_terms & content_terms)
    return overlap / math.sqrt(len(query_terms) * len(content_terms))
