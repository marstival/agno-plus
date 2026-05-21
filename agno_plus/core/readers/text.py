"""Plain-text and PDF readers for the agno-plus ingestion pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agno_plus.core.models import Document


class TextReader:
    """Reads .txt and .md files as a single Document."""

    EXTENSIONS = {".txt", ".md"}

    def read(self, source: bytes | str, filename: str = "text.txt", **_: Any) -> list[Document]:
        if isinstance(source, bytes):
            content = source.decode("utf-8", errors="replace")
        else:
            content = source
        return [
            Document(
                id=f"text_{uuid.uuid4().hex[:8]}",
                content=content,
                source_type="text",
                source_name=filename,
                metadata={"filename": filename},
            )
        ]


class PdfReader:
    """Reads .pdf files by extracting text from each page.

    Requires pypdf: pip install pypdf
    """

    EXTENSIONS = {".pdf"}

    def read(self, source: bytes | str, filename: str = "document.pdf", **_: Any) -> list[Document]:
        try:
            import pypdf
        except ImportError:
            raise ImportError("pypdf is required for PDF ingestion. Install it with: pip install pypdf")

        import io

        if isinstance(source, str):
            source = source.encode()

        reader = pypdf.PdfReader(io.BytesIO(source))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)

        full_text = "\n\n".join(pages)
        return [
            Document(
                id=f"pdf_{uuid.uuid4().hex[:8]}",
                content=full_text,
                source_type="pdf",
                source_name=filename,
                metadata={"filename": filename, "page_count": len(reader.pages)},
            )
        ]
