from __future__ import annotations

import hashlib
import unicodedata


def normalized_memory_key(content: str) -> str:
    """Return a stable key for agent-scoped durable-memory deduplication."""

    normalized = unicodedata.normalize("NFKC", content).casefold()
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
