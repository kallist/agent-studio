from __future__ import annotations

import hashlib
import math
import re

from openai import AsyncOpenAI


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


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str, dimensions: int = 1536) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = dimensions

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
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]


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
