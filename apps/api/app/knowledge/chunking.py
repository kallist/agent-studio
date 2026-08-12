from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.knowledge.parsers import ParsedSection


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    content: str
    token_count: int
    metadata: dict[str, Any]


class TextChunker:
    """Paragraph-aware character chunker with bounded overlap."""

    def __init__(self, target_chars: int = 900, overlap_chars: int = 140) -> None:
        if target_chars < 200 or overlap_chars < 0 or overlap_chars >= target_chars:
            raise ValueError("Invalid chunk size or overlap.")
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def chunk(self, sections: list[ParsedSection]) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for section in sections:
            text = _normalize(section.text)
            if not text:
                continue
            for content, start, end in self._split(text):
                metadata = {
                    **section.metadata,
                    "start_char": start,
                    "end_char": end,
                }
                drafts.append(
                    ChunkDraft(
                        index=len(drafts),
                        content=content,
                        token_count=len(_terms(content)),
                        metadata=metadata,
                    )
                )
        return drafts

    def _split(self, text: str) -> list[tuple[str, int, int]]:
        if len(text) <= self.target_chars:
            return [(text, 0, len(text))]

        chunks: list[tuple[str, int, int]] = []
        start = 0
        while start < len(text):
            target_end = min(start + self.target_chars, len(text))
            end = target_end
            if target_end < len(text):
                floor = start + self.target_chars // 2
                candidates = [
                    text.rfind("\n\n", floor, target_end),
                    text.rfind(". ", floor, target_end),
                    text.rfind("。", floor, target_end),
                    text.rfind("\n", floor, target_end),
                ]
                boundary = max(candidates)
                if boundary >= floor:
                    end = boundary + (2 if text[boundary : boundary + 2] in {"\n\n", ". "} else 1)
            content = text[start:end].strip()
            if content:
                chunks.append((content, start, end))
            if end >= len(text):
                break
            next_start = max(start + 1, end - self.overlap_chars)
            while next_start < end and not text[next_start].isspace():
                next_start += 1
            start = min(next_start + 1, end)
        return chunks


def _normalize(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\r\n?", "\n", text)).strip()


def _terms(text: str) -> list[str]:
    return re.findall(r"[\w\u3400-\u9fff]+", text.lower())
