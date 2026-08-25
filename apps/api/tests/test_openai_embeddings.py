from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from httpx import Request, Response
from openai import APITimeoutError, AuthenticationError, RateLimitError

from app.domain.contracts import KnowledgeSearchRequest
from app.domain.errors import KnowledgeProviderError, KnowledgeValidationError
from app.knowledge.embeddings import DeterministicEmbeddingProvider, OpenAIEmbeddingProvider
from app.knowledge.service import KnowledgeService


class _FakeEmbeddings:
    def __init__(self, *, bad_dimensions: bool = False, non_finite: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.bad_dimensions = bad_dimensions
        self.non_finite = non_finite
        self.offset = 0

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        inputs = cast(list[str], kwargs["input"])
        size = 255 if self.bad_dimensions else 256
        data = []
        for index in range(len(inputs)):
            vector = [0.0] * size
            vector[0] = float("nan") if self.non_finite else float(self.offset + index)
            data.append(SimpleNamespace(index=index, embedding=vector))
        self.offset += len(inputs)
        return SimpleNamespace(data=list(reversed(data)), model=kwargs["model"])


class _FakeClient:
    def __init__(self, embeddings: _FakeEmbeddings) -> None:
        self.embeddings = embeddings
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RaisingEmbeddings:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, **_kwargs: object) -> SimpleNamespace:
        raise self.error


@pytest.mark.asyncio
async def test_openai_embeddings_request_native_256_dimensions_batch_and_preserve_order() -> None:
    embeddings_api = _FakeEmbeddings()
    client = _FakeClient(embeddings_api)
    provider = OpenAIEmbeddingProvider(
        "unused-test-key",
        "text-embedding-3-small",
        client=cast(Any, client),
    )

    vectors = await provider.embed([f"text-{index}" for index in range(129)])

    assert provider.dimensions == 256
    assert [len(cast(list[str], call["input"])) for call in embeddings_api.calls] == [128, 1]
    assert all(call["dimensions"] == 256 for call in embeddings_api.calls)
    assert [vector[0] for vector in vectors] == [float(index) for index in range(129)]
    await provider.close()
    assert client.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad_dimensions", "non_finite"),
    [(True, False), (False, True)],
)
async def test_openai_embeddings_fail_closed_on_invalid_vector_contract(
    bad_dimensions: bool, non_finite: bool
) -> None:
    provider = OpenAIEmbeddingProvider(
        "unused-test-key",
        "text-embedding-3-small",
        client=cast(
            Any,
            _FakeClient(
                _FakeEmbeddings(
                    bad_dimensions=bad_dimensions,
                    non_finite=non_finite,
                )
            ),
        ),
    )

    with pytest.raises(KnowledgeProviderError, match="invalid vector contract"):
        await provider.embed(["test"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "safe_message"),
    [
        (
            AuthenticationError(
                "provider body mentioning a credential",
                response=Response(401, request=Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "authentication failed",
        ),
        (
            RateLimitError(
                "provider rate-limit body",
                response=Response(429, request=Request("POST", "https://api.openai.com")),
                body=None,
            ),
            "rate limited",
        ),
        (
            APITimeoutError(request=Request("POST", "https://api.openai.com")),
            "temporarily unavailable",
        ),
    ],
)
async def test_openai_embedding_errors_are_safe_and_drop_provider_exception_context(
    error: Exception, safe_message: str
) -> None:
    provider = OpenAIEmbeddingProvider(
        "unused-test-key",
        "text-embedding-3-small",
        client=cast(Any, _FakeClient(cast(Any, _RaisingEmbeddings(error)))),
    )

    with pytest.raises(KnowledgeProviderError, match=safe_message) as caught:
        await provider.embed(["test"])

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_search_fails_closed_when_completed_chunks_mix_embedding_contracts(
    tmp_path: Path,
) -> None:
    base_id = uuid4()
    embeddings = DeterministicEmbeddingProvider()

    class _MixedRepository:
        async def get_base(self, _knowledge_base_id: object) -> SimpleNamespace:
            return SimpleNamespace(
                name="mixed",
                embedding_provider=embeddings.name,
                embedding_model=embeddings.model,
                embedding_dimensions=embeddings.dimensions,
            )

        async def active_embedding_contracts(
            self, _knowledge_base_id: object
        ) -> set[tuple[str, str, int]]:
            return {
                (embeddings.name, embeddings.model, embeddings.dimensions),
                ("openai", "text-embedding-3-small", 256),
            }

    service = KnowledgeService(
        cast(Any, _MixedRepository()),
        cast(Any, SimpleNamespace()),
        embeddings,
        tmp_path,
        1_000,
    )

    with pytest.raises(KnowledgeValidationError, match="requires re-ingestion"):
        await service.search(
            [base_id], KnowledgeSearchRequest(query="test", top_k=1)
        )
