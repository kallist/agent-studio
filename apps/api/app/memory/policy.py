from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.memory.contracts import MemoryKind, MemoryMatch, MemoryRecord

_EXPLICIT_PATTERNS = (
    re.compile(r"\bremember(?:\s+that|\s*:)?\s+(.+)$", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:请)?记住[：:，,\s]*(.+)$", re.DOTALL),
)
_STABLE_FACT_PATTERNS = (
    re.compile(
        r"\bmy\s+(name|preferred language|timezone|favorite colou?r|project codename)\s+is\s+(.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"我的(名字|偏好语言|时区|最喜欢的颜色|项目代号)是(.+)$", re.DOTALL),
)
_SENSITIVE = re.compile(
    r"\b(password|passcode|secret|api[ _-]?key|access[ _-]?token|credit[ _-]?card|"
    r"social security|private key)\b|密码|口令|密钥|令牌|身份证|银行卡",
    re.IGNORECASE,
)
_INSTRUCTIONAL = re.compile(
    r"\b(ignore|disregard|override|always|never|must|system prompt|developer message)\b|"
    r"忽略|覆盖|必须|永远|系统提示|开发者消息",
    re.IGNORECASE,
)
_ASCII_WORD = re.compile(r"[a-z0-9]+")
_CHINESE_SEQUENCE = re.compile(r"[\u4e00-\u9fff]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "does",
    "i",
    "is",
    "it",
    "me",
    "my",
    "of",
    "remember",
    "that",
    "the",
    "what",
    "you",
}


class MemoryPolicy:
    """Deterministic first-version write and retrieval policy."""

    def __init__(
        self,
        *,
        ttl_days: int = 180,
        relevance_threshold: float = 0.25,
        max_results: int = 5,
        max_context_chars: int = 1_500,
    ) -> None:
        self.ttl_days = ttl_days
        self.relevance_threshold = relevance_threshold
        self.max_results = max_results
        self.max_context_chars = max_context_chars

    def propose_write(
        self,
        *,
        agent_id: UUID,
        run_id: UUID,
        user_input: str,
        now: datetime | None = None,
    ) -> MemoryRecord | None:
        content: str | None = None
        importance = 0.0
        source = ""

        for pattern in _EXPLICIT_PATTERNS:
            match = pattern.search(user_input.strip())
            if match:
                content = match.group(1)
                importance = 0.9
                source = "explicit_remember"
                break

        if content is None:
            for pattern in _STABLE_FACT_PATTERNS:
                match = pattern.search(user_input.strip())
                if match:
                    content = " ".join(part.strip() for part in match.groups())
                    importance = 0.7
                    source = "stable_fact_allowlist"
                    break

        if content is None:
            return None

        normalized = " ".join(content.split()).strip(" .。!?！？")
        if not normalized or len(normalized) > 500:
            return None
        if _SENSITIVE.search(normalized) or _INSTRUCTIONAL.search(normalized):
            return None

        timestamp = now or datetime.now(UTC)
        return MemoryRecord(
            agent_id=agent_id,
            kind=MemoryKind.LONG_TERM,
            content=normalized,
            importance=importance,
            source_run_id=run_id,
            created_at=timestamp,
            expires_at=timestamp + timedelta(days=self.ttl_days),
            metadata={"write_reason": source},
        )

    def rank(
        self,
        query: str,
        records: list[MemoryRecord],
        *,
        now: datetime | None = None,
    ) -> list[MemoryMatch]:
        timestamp = now or datetime.now(UTC)
        query_terms = _terms(query)
        if not query_terms:
            return []

        matches: list[MemoryMatch] = []
        for record in records:
            if record.kind is not MemoryKind.LONG_TERM:
                continue
            if record.expires_at is not None and record.expires_at <= timestamp:
                continue
            relevance = _relevance(query_terms, _terms(record.content))
            if relevance < self.relevance_threshold:
                continue
            age_days = max(0.0, (timestamp - record.created_at).total_seconds() / 86_400)
            recency = 1 / (1 + age_days / 30)
            score = 0.50 * relevance + 0.30 * record.importance + 0.20 * recency
            matches.append(
                MemoryMatch(
                    record=record,
                    score=round(score, 6),
                    relevance=round(relevance, 6),
                    recency=round(recency, 6),
                    importance=record.importance,
                )
            )

        matches.sort(
            key=lambda item: (item.score, item.record.created_at, str(item.record.id)),
            reverse=True,
        )
        selected: list[MemoryMatch] = []
        used_chars = 0
        for match in matches:
            if len(selected) >= self.max_results:
                break
            content_size = len(match.record.content)
            if selected and used_chars + content_size > self.max_context_chars:
                continue
            selected.append(match)
            used_chars += content_size
        return selected


def _terms(text: str) -> set[str]:
    lowered = text.casefold()
    terms = {word for word in _ASCII_WORD.findall(lowered) if word not in _STOP_WORDS}
    for sequence in _CHINESE_SEQUENCE.findall(lowered):
        if len(sequence) == 1:
            terms.add(sequence)
            continue
        terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return terms


def _relevance(query_terms: set[str], content_terms: set[str]) -> float:
    if not query_terms or not content_terms:
        return 0.0
    overlap = len(query_terms & content_terms)
    return min(1.0, (2 * overlap) / (len(query_terms) + len(content_terms)))
