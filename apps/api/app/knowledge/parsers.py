from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.errors import DocumentParsingError


@dataclass(frozen=True)
class ParsedSection:
    text: str
    metadata: dict[str, Any]


class DocumentParser(Protocol):
    def parse(self, path: Path) -> list[ParsedSection]: ...


class TextParser:
    def __init__(self, max_extracted_chars: int = 2_000_000) -> None:
        self.max_extracted_chars = max_extracted_chars

    def parse(self, path: Path) -> list[ParsedSection]:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParsingError("Text documents must use UTF-8 encoding.") from exc
        if "\x00" in content:
            raise DocumentParsingError("Text document contains binary data.")
        if not content.strip():
            raise DocumentParsingError("Document does not contain searchable text.")
        if len(content) > self.max_extracted_chars:
            raise DocumentParsingError(
                f"Document exceeds the {self.max_extracted_chars} character extracted text limit."
            )
        return [ParsedSection(text=content, metadata={})]


class MarkdownParser(TextParser):
    _heading = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

    def parse(self, path: Path) -> list[ParsedSection]:
        content = super().parse(path)[0].text
        matches = list(self._heading.finditer(content))
        if not matches:
            return [ParsedSection(text=content, metadata={"format": "markdown"})]
        sections: list[ParsedSection] = []
        if matches[0].start() > 0 and content[: matches[0].start()].strip():
            sections.append(
                ParsedSection(
                    text=content[: matches[0].start()], metadata={"format": "markdown"}
                )
            )
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            sections.append(
                ParsedSection(
                    text=content[match.start() : end],
                    metadata={
                        "format": "markdown",
                        "heading": match.group(2).strip()[:500],
                        "heading_level": len(match.group(1)),
                    },
                )
            )
        return sections


class PdfParser:
    def __init__(
        self, max_pages: int = 500, max_extracted_chars: int = 2_000_000
    ) -> None:
        self.max_pages = max_pages
        self.max_extracted_chars = max_extracted_chars

    def parse(self, path: Path) -> list[ParsedSection]:
        try:
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise DocumentParsingError("Encrypted PDFs are not supported.")
            if len(reader.pages) > self.max_pages:
                raise DocumentParsingError(f"PDF exceeds the {self.max_pages} page limit.")
            sections: list[ParsedSection] = []
            extracted_chars = 0
            for index, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                extracted_chars += len(text)
                if extracted_chars > self.max_extracted_chars:
                    raise DocumentParsingError(
                        "PDF exceeds the configured extracted text limit."
                    )
                sections.append(ParsedSection(text=text, metadata={"page": index + 1}))
        except DocumentParsingError:
            raise
        except (PdfReadError, OSError, ValueError) as exc:
            raise DocumentParsingError("PDF parser could not read this file.") from exc
        if not any(section.text.strip() for section in sections):
            raise DocumentParsingError(
                "PDF contains no extractable text; scanned PDFs require OCR, which is not enabled."
            )
        return sections


def parser_for(mime_type: str, max_extracted_chars: int = 2_000_000) -> DocumentParser:
    if mime_type == "text/plain":
        return TextParser(max_extracted_chars)
    if mime_type == "text/markdown":
        return MarkdownParser(max_extracted_chars)
    if mime_type == "application/pdf":
        return PdfParser(max_extracted_chars=max_extracted_chars)
    raise DocumentParsingError(f"No parser is registered for MIME type '{mime_type}'.")
