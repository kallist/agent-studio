from __future__ import annotations

import hashlib
import math
import re

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.domain.errors import KnowledgeProviderError

_OPENAI_EMBEDDING_DIMENSIONS = 256
_OPENAI_EMBEDDING_BATCH_SIZE = 128


class DeterministicEmbeddingProvider:
    """Small dependency-free feature-hashing embedder for local runs and tests."""

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return f"feature-hash-v1-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embed_text(text, self._dimensions) for text in texts]

    async def close(self) -> None:
        return None


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._model = model
        self._dimensions = _OPENAI_EMBEDDING_DIMENSIONS

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), _OPENAI_EMBEDDING_BATCH_SIZE):
                batch = texts[start : start + _OPENAI_EMBEDDING_BATCH_SIZE]
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                    dimensions=self._dimensions,
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                if len(ordered) != len(batch) or [item.index for item in ordered] != list(
                    range(len(batch))
                ):
                    raise KnowledgeProviderError(
                        "OpenAI embeddings returned an invalid batch index contract."
                    )
                for item in ordered:
                    vector = list(item.embedding)
                    if len(vector) != self._dimensions or not all(
                        math.isfinite(value) for value in vector
                    ):
                        raise KnowledgeProviderError(
                            "OpenAI embeddings returned an invalid vector contract."
                        )
                    vectors.append(vector)
        except AuthenticationError:
            raise KnowledgeProviderError("OpenAI embeddings authentication failed.") from None
        except RateLimitError:
            raise KnowledgeProviderError("OpenAI embeddings were rate limited.") from None
        except (APITimeoutError, APIConnectionError):
            raise KnowledgeProviderError(
                "OpenAI embeddings are temporarily unavailable."
            ) from None
        except APIError:
            raise KnowledgeProviderError("OpenAI embeddings request failed.") from None
        return vectors

    async def close(self) -> None:
        await self._client.close()


def _features(text: str) -> list[str]:
    normalized = text.lower()
    words = re.findall(r"[a-z0-9_]+", normalized)
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    cjk_ngrams = [cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))]
    compact = re.sub(r"\s+", " ", normalized)
    char_ngrams = [compact[index : index + 3] for index in range(max(0, len(compact) - 2))]
    return words + cjk_ngrams + char_ngrams


def _embed_text(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for feature in _features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % dimensions
        vector[index] += 1.0 if (value >> 8) & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        return [value / norm for value in vector]
    return vector
