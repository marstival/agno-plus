"""IntelligentPdfReader — 3-layer layout-aware PDF ingestion.

Layer A (page parser)  → pdfplumber extracts per-page tables and text regions
Layer B (classifier)   → TABLE (pdfplumber-detected), TEXT (prose), NOTE (short)
Layer C (extractor)    → TableRow / NoteItem records → one Document per block

Falls back to pypdf plain-text extraction when pdfplumber finds no content
(scanned PDFs without embedded text).

Requires: pip install agno-plus[pdf]
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agno_plus.core.models import Document

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({".pdf"})


class _BlockType(str, Enum):
    TABLE = "table"
    TEXT = "text"
    NOTE = "note"


@dataclass
class _PdfBlock:
    block_type: _BlockType
    page_number: int            # 1-based
    raw_cells: list[list[str]] | None = None   # TABLE blocks only
    raw_text: str | None = None                # TEXT / NOTE blocks only


class IntelligentPdfReader:
    """Layout-aware PDF reader with numeric table detection.

    Returns one Document per detected block (table or prose section). Each table
    block renders as a Markdown table. Falls back to pypdf page-by-page text for
    scanned PDFs where pdfplumber finds no embedded content.

    Shares the extract_tables() contract with SpreadsheetReader — same output
    shape, so a PDF with numeric tables can be ingested as a structured domain.
    """

    EXTENSIONS = SUPPORTED_EXTENSIONS

    def read(self, source: bytes | str, filename: str = "document.pdf", **_: Any) -> list[Document]:
        if isinstance(source, str):
            source = source.encode()
        blocks = self._parse(source)
        if not blocks:
            return self._fallback_pypdf(source, filename)
        return self._to_documents(blocks, filename)

    def extract_tables(self, source: bytes | str, filename: str = "document.pdf") -> list[dict]:
        """Return raw table data for structured domain ingestion.

        Each entry: {"headers": [...], "rows": [{col: val, ...}, ...]}.
        Only TABLE blocks are returned. Compatible with SpreadsheetReader.extract_tables().
        """
        if isinstance(source, str):
            source = source.encode()
        blocks = self._parse(source)
        tables = []
        for block in blocks:
            if block.block_type == _BlockType.TABLE and block.raw_cells:
                table = self._cells_to_table_dict(block.raw_cells)
                if table:
                    tables.append(table)
        return tables

    # ------------------------------------------------------------------
    # Layer A — page parser
    # ------------------------------------------------------------------

    def _parse(self, pdf_bytes: bytes) -> list[_PdfBlock]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required for IntelligentPdfReader. "
                "Install with: pip install agno-plus[pdf]"
            )

        blocks: list[_PdfBlock] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    blocks.extend(self._parse_page(page, page_num))
        except Exception as exc:
            logger.warning("pdfplumber failed to open PDF: %s", exc)
        return blocks

    def _parse_page(self, page: Any, page_num: int) -> list[_PdfBlock]:
        blocks: list[_PdfBlock] = []

        try:
            detected = page.find_tables()
        except Exception:
            detected = []

        table_bboxes: list[tuple[float, float, float, float]] = []

        for tbl in detected:
            try:
                cells = tbl.extract()
                if not cells:
                    continue
                normalized = [
                    [str(cell).strip() if cell is not None else "" for cell in row]
                    for row in cells
                ]
                if any(any(row) for row in normalized):
                    blocks.append(_PdfBlock(
                        block_type=_BlockType.TABLE,
                        page_number=page_num,
                        raw_cells=normalized,
                    ))
                    table_bboxes.append(tbl.bbox)
            except Exception as exc:
                logger.debug("Table extraction failed page %d: %s", page_num, exc)

        non_table = self._extract_non_table_text(page, table_bboxes)
        for chunk in re.split(r"\n{2,}", non_table):
            chunk = chunk.strip()
            if not chunk:
                continue
            line_count = chunk.count("\n") + 1
            btype = _BlockType.TEXT if line_count >= 3 else _BlockType.NOTE
            blocks.append(_PdfBlock(block_type=btype, page_number=page_num, raw_text=chunk))

        return blocks

    def _extract_non_table_text(
        self, page: Any, table_bboxes: list[tuple[float, float, float, float]]
    ) -> str:
        if not table_bboxes:
            return page.extract_text() or ""

        def not_in_any_table(obj: dict) -> bool:
            ox0 = obj.get("x0", 0)
            ox1 = obj.get("x1", 0)
            otop = obj.get("top", 0)
            obot = obj.get("bottom", 0)
            for tx0, ty0, tx1, ty1 in table_bboxes:
                if ox0 >= tx0 - 2 and ox1 <= tx1 + 2 and otop >= ty0 - 2 and obot <= ty1 + 2:
                    return False
            return True

        try:
            return page.filter(not_in_any_table).extract_text() or ""
        except Exception:
            return page.extract_text() or ""

    # ------------------------------------------------------------------
    # Layer B/C — classify and render
    # ------------------------------------------------------------------

    def _cells_to_table_dict(self, cells: list[list[str]]) -> dict | None:
        """Convert raw cell array to {headers, rows} dict."""
        if len(cells) < 2:
            return None
        raw_headers = cells[0]
        if not any(raw_headers):
            return None

        seen: dict[str, int] = {}
        unique: list[str] = []
        for i, h in enumerate(raw_headers):
            h = h.strip() or f"col_{i}"
            if h in seen:
                seen[h] += 1
                unique.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique.append(h)

        rows = []
        for row in cells[1:]:
            record = {unique[i]: (row[i] if i < len(row) else "") for i in range(len(unique))}
            if any(v.strip() for v in record.values()):
                rows.append(record)

        return {"headers": unique, "rows": rows} if rows else None

    def _render_table(self, block: _PdfBlock) -> str:
        assert block.raw_cells
        table = self._cells_to_table_dict(block.raw_cells)
        if not table:
            return ""
        headers = table["headers"]
        rows = table["rows"]
        lines = [
            f"### Table (page {block.page_number})",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |" for r in rows),
        ]
        return "\n".join(lines)

    def _render_text(self, block: _PdfBlock) -> str:
        assert block.raw_text
        label = "Text" if block.block_type == _BlockType.TEXT else "Note"
        return f"### {label} (page {block.page_number})\n{block.raw_text}"

    def _to_documents(self, blocks: list[_PdfBlock], filename: str) -> list[Document]:
        docs: list[Document] = []
        for block in blocks:
            content = (
                self._render_table(block)
                if block.block_type == _BlockType.TABLE
                else self._render_text(block)
            )
            if not content:
                continue
            docs.append(Document(
                id=f"pdf_{uuid.uuid4().hex[:8]}",
                content=content,
                source_type="pdf",
                source_name=filename,
                metadata={
                    "filename": filename,
                    "block_type": block.block_type.value,
                    "page_number": block.page_number,
                },
            ))
        return docs

    # ------------------------------------------------------------------
    # Fallback — pypdf text extraction for scanned PDFs
    # ------------------------------------------------------------------

    def _fallback_pypdf(self, pdf_bytes: bytes, filename: str) -> list[Document]:
        logger.info("pdfplumber found no content in %s — falling back to pypdf", filename)
        try:
            import pypdf
        except ImportError:
            raise ImportError("pypdf is required as a PDF fallback. Install with: pip install pypdf")

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n\n".join(p for p in pages if p.strip())
        if not full_text:
            return []
        return [Document(
            id=f"pdf_{uuid.uuid4().hex[:8]}",
            content=full_text,
            source_type="pdf",
            source_name=filename,
            metadata={
                "filename": filename,
                "block_type": "text",
                "page_count": len(reader.pages),
            },
        )]
