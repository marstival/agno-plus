"""IntelligentPdfReader — 3-layer layout-aware PDF ingestion.

Layer A (page parser)  → pdfplumber extracts per-page tables and text regions
Layer B (classifier)   → TABLE (pdfplumber-detected), TEXT (prose), NOTE (short)
Layer C (extractor)    → TableRow / NoteItem records → one Document per block

Header recovery strategy (in priority order):
  1. Text region just above the table bbox — words are assigned to columns using
     the table's own cell x-ranges, so multi-word headers like "UNIT PRICE" and
     "LINE TOTAL" are grouped correctly.
  2. First row of extracted cells, if it passes the _is_header_row heuristic.
  3. Generic col_0, col_1, … names when neither of the above applies.

Falls back to pypdf plain-text extraction when pdfplumber finds no content
(scanned PDFs without embedded text).

Requires: pip install agno-plus[pdf]
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agno_plus.core.models import Document

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({".pdf"})

# How far above the table top (in PDF points) to search for a header row.
_HEADER_SEARCH_MARGIN = 40.0
# A word is considered "close to the table" if its bottom edge is within this
# many points of the table's top boundary.
_HEADER_WORD_PROXIMITY = 25.0


class _BlockType(str, Enum):
    TABLE = "table"
    TEXT = "text"
    NOTE = "note"


@dataclass
class _PdfBlock:
    block_type: _BlockType
    page_number: int                              # 1-based
    raw_cells: list[list[str]] | None = None      # TABLE blocks only
    raw_text: str | None = None                   # TEXT / NOTE blocks only
    external_headers: list[str] | None = None     # headers found above the table


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
                table = self._cells_to_table_dict(block.raw_cells, block.external_headers)
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
                if not any(any(row) for row in normalized):
                    continue

                external_headers = self._find_header_above_table(page, tbl)
                blocks.append(_PdfBlock(
                    block_type=_BlockType.TABLE,
                    page_number=page_num,
                    raw_cells=normalized,
                    external_headers=external_headers,
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

    def _find_header_above_table(self, page: Any, tbl: Any) -> list[str] | None:
        """Find column labels in the text region just above the table bbox.

        Assigns words to columns using the table's own cell x-ranges so that
        multi-word headers like "UNIT PRICE" or "LINE TOTAL" are grouped correctly.
        Returns None if no usable header row is found.
        """
        try:
            x0, top, x1, _bottom = tbl.bbox
            search_top = max(0, top - _HEADER_SEARCH_MARGIN)
            if search_top >= top:
                return None

            # Get column x-ranges from the first row's cell bounding boxes
            if not tbl.rows:
                return None
            first_row_cells = [c for c in tbl.rows[0].cells if c is not None]
            if not first_row_cells:
                return None
            col_ranges = [(c[0], c[2]) for c in first_row_cells]  # (x0, x1) per column
            col_count = len(col_ranges)

            # Extract words from the region above the table
            header_region = page.crop((x0, search_top, x1, top))
            words = header_region.extract_words(keep_blank_chars=False)
            if not words:
                return None

            # Keep only words whose bottom edge is close to the table top —
            # i.e. the last text line before the table starts.
            close_words = [w for w in words if (top - w.get("bottom", 0)) <= _HEADER_WORD_PROXIMITY]
            if not close_words:
                close_words = words  # fallback: use all words in region

            # Assign each word to the column whose x-range contains the word's center.
            # Fall back to nearest center when the word center falls between columns.
            col_words: dict[int, list[str]] = {i: [] for i in range(col_count)}
            for word in close_words:
                wx_center = (word["x0"] + word["x1"]) / 2
                assigned: int | None = None
                for ci, (cx0, cx1) in enumerate(col_ranges):
                    if cx0 <= wx_center <= cx1:
                        assigned = ci
                        break
                if assigned is None:
                    assigned = min(
                        range(col_count),
                        key=lambda ci: abs((col_ranges[ci][0] + col_ranges[ci][1]) / 2 - wx_center),
                    )
                col_words[assigned].append(word["text"])

            headers = [" ".join(col_words[i]) for i in range(col_count)]

            # Validate: at least half the columns have text, and they look like labels.
            non_empty = [h for h in headers if h.strip()]
            if len(non_empty) < max(1, col_count // 2):
                return None
            if not self._is_header_row(non_empty):
                return None

            logger.debug("Recovered headers above table: %s", headers)
            return headers

        except Exception as exc:
            logger.debug("Header-above-table search failed: %s", exc)
            return None

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

    def _is_header_row(self, row: list[str]) -> bool:
        """Return True if this row looks like column labels rather than data values.

        More than 1/3 numeric cells signals a data row, not a header row.
        """
        non_empty = [c.strip() for c in row if c.strip()]
        if not non_empty:
            return False
        numeric_count = 0
        for cell in non_empty:
            cleaned = cell.lstrip("$€£¥+-(").rstrip("%)").replace(",", "").replace(" ", "")
            try:
                float(cleaned)
                numeric_count += 1
            except ValueError:
                pass
        return numeric_count <= len(non_empty) / 3

    def _cells_to_table_dict(
        self,
        cells: list[list[str]],
        forced_headers: list[str] | None = None,
    ) -> dict | None:
        """Convert raw cell array to {headers, rows} dict.

        Header resolution priority:
          1. forced_headers — labels recovered from the text above the table.
          2. cells[0] if it passes _is_header_row.
          3. Generic col_0, col_1, … names.
        """
        if not cells:
            return None

        if forced_headers:
            raw_headers = forced_headers
            data_rows = cells
        elif self._is_header_row(cells[0]):
            raw_headers = cells[0]
            data_rows = cells[1:]
        else:
            width = max(len(r) for r in cells)
            raw_headers = [f"col_{i}" for i in range(width)]
            data_rows = cells

        if not any(h.strip() for h in raw_headers) or not data_rows:
            return None

        # Deduplicate headers
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
        for row in data_rows:
            record = {unique[i]: (row[i] if i < len(row) else "") for i in range(len(unique))}
            if any(v.strip() for v in record.values()):
                rows.append(record)

        return {"headers": unique, "rows": rows} if rows else None

    def _render_table(self, block: _PdfBlock) -> str:
        assert block.raw_cells
        table = self._cells_to_table_dict(block.raw_cells, block.external_headers)
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
