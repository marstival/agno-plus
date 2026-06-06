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

# Stream extraction — used for borderless tables (no drawn cell lines).
_STREAM_Y_TOL    =  6.0   # words within this vertical range → same row
_STREAM_CELL_GAP = 15.0   # horizontal gap larger than this splits cells
_STREAM_ROW_GAP  = 48.0   # vertical gap larger than this splits table blocks
_STREAM_COL_TOL  = 40.0   # column centers within this range → same column
_STREAM_MIN_COLS =  2     # minimum columns to be considered a table
_STREAM_MIN_ROWS =  2     # minimum rows to be considered a table


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
    headings: list[str] = field(default_factory=list)  # heading stack at block emission


# ---------------------------------------------------------------------------
# Heading detection — maintains a section stack as the reader walks blocks
# ---------------------------------------------------------------------------


_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+([A-Z]\S.*?)\s*$")
_ROMAN_HEADING_RE = re.compile(r"^([IVX]+)\.\s+([A-Z]\S.*?)\s*$")


class _HeadingStack:
    """Depth-aware heading stack updated as the reader walks PDF blocks.

    Numbered headings ("3.1 Foo") slot in by dot depth. Plain uppercase single
    lines ("INVOICE", "PAYMENT TERMS") replace the stack at depth 1.
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []  # (depth, text)

    def update_from_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        m = _NUMBERED_HEADING_RE.match(line)
        if m:
            depth = m.group(1).count(".") + 1
            self._push(depth, line)
            return
        if _ROMAN_HEADING_RE.match(line):
            self._push(1, line)
            return
        if self._is_all_caps_heading(line):
            self._push(1, line)

    def _push(self, depth: int, text: str) -> None:
        while self._stack and self._stack[-1][0] >= depth:
            self._stack.pop()
        self._stack.append((depth, text))

    @staticmethod
    def _is_all_caps_heading(line: str) -> bool:
        """Conservative all-caps rule: short standalone line, no terminal punctuation,
        every word ≥ 2 alphabetic chars (rejects column-header rows like 'Q T Y')."""
        if not (4 <= len(line) <= 40):
            return False
        words = line.split()
        if not (1 <= len(words) <= 4):
            return False
        if not all(w.isupper() and sum(c.isalpha() for c in w) >= 2 for w in words):
            return False
        if line[-1] in ".:":
            return False
        return True

    @property
    def path(self) -> list[str]:
        return [text for _, text in self._stack]


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
        stack = _HeadingStack()
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    for blk in self._parse_page(page, page_num):
                        # Text blocks can introduce headings; tables inherit
                        # the stack state from preceding text on the same page.
                        if blk.raw_text:
                            for line in blk.raw_text.splitlines():
                                stack.update_from_line(line)
                        blk.headings = list(stack.path)
                        blocks.append(blk)
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

        if not table_bboxes:
            for cells, bbox in self._stream_extract_tables(page):
                blocks.append(_PdfBlock(
                    block_type=_BlockType.TABLE,
                    page_number=page_num,
                    raw_cells=cells,
                    external_headers=None,
                ))
                table_bboxes.append(bbox)

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

    def _stream_extract_tables(
        self, page: Any
    ) -> list[tuple[list[list[str]], tuple[float, float, float, float]]]:
        """Detect tables in pages without drawn borders using word-position analysis.

        Algorithm:
          1. Group words into horizontal bands by y-proximity (_STREAM_Y_TOL).
          2. Split each band into cells at x-gaps > _STREAM_CELL_GAP.
          3. Split rows into table candidates at vertical gaps > _STREAM_ROW_GAP.
          4. Cluster cell x-centers per candidate (_STREAM_COL_TOL) to form columns.
          5. Assign each cell to the nearest column center.

        Returns (cells_matrix, page_bbox) pairs. bbox is used to exclude the
        stream table region from plain-text extraction.
        """
        try:
            words = page.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
        except Exception:
            return []
        if not words:
            return []

        # Step 1 — band words by y-top proximity (use first word of band as anchor).
        words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))
        row_bands: list[list[dict]] = []
        for word in words_sorted:
            placed = False
            for band in row_bands:
                if abs(word["top"] - band[0]["top"]) <= _STREAM_Y_TOL:
                    band.append(word)
                    placed = True
                    break
            if not placed:
                row_bands.append([word])

        # Step 2 — split each band into cells; keep only multi-column rows.
        # Entry: (y_top, y_bottom, [(x_center, text), ...])
        structured_rows: list[tuple[float, float, list[tuple[float, str]]]] = []
        for band in row_bands:
            band.sort(key=lambda w: w["x0"])
            cells: list[tuple[float, str]] = []
            cur: list[dict] = [band[0]]
            for word in band[1:]:
                if word["x0"] - cur[-1]["x1"] > _STREAM_CELL_GAP:
                    cx = (cur[0]["x0"] + cur[-1]["x1"]) / 2
                    cells.append((cx, " ".join(w["text"] for w in cur)))
                    cur = [word]
                else:
                    cur.append(word)
            cx = (cur[0]["x0"] + cur[-1]["x1"]) / 2
            cells.append((cx, " ".join(w["text"] for w in cur)))
            if len(cells) >= _STREAM_MIN_COLS:
                y_top = min(w["top"] for w in band)
                y_bot = max(w["bottom"] for w in band)
                structured_rows.append((y_top, y_bot, cells))

        if not structured_rows:
            return []

        # Step 3 — split into candidate groups at large vertical gaps.
        groups: list[list[tuple[float, float, list[tuple[float, str]]]]] = []
        cur_group: list[tuple[float, float, list[tuple[float, str]]]] = [structured_rows[0]]
        for i in range(1, len(structured_rows)):
            prev_bot = structured_rows[i - 1][1]
            curr_top = structured_rows[i][0]
            if curr_top - prev_bot > _STREAM_ROW_GAP:
                groups.append(cur_group)
                cur_group = []
            cur_group.append(structured_rows[i])
        groups.append(cur_group)

        # Step 4 — for each group: cluster columns, assign cells, compute bbox.
        results: list[tuple[list[list[str]], tuple[float, float, float, float]]] = []
        for group in groups:
            if len(group) < _STREAM_MIN_ROWS:
                continue
            all_cx = [cx for _, _, cells in group for cx, _ in cells]
            col_centers = self._cluster_centers(all_cx, _STREAM_COL_TOL)
            if len(col_centers) < _STREAM_MIN_COLS:
                continue

            table_rows: list[list[str]] = []
            for _, _, cells in group:
                row: list[str] = [""] * len(col_centers)
                for cx, text in cells:
                    ci = min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - cx))
                    row[ci] = (row[ci] + " " + text).strip() if row[ci] else text
                table_rows.append(row)

            gy0 = group[0][0]
            gy1 = group[-1][1]
            gx0 = min(w["x0"] for w in words if gy0 - 2 <= w["top"] <= gy1 + 2)
            gx1 = max(w["x1"] for w in words if gy0 - 2 <= w["top"] <= gy1 + 2)
            results.append((table_rows, (gx0, gy0, gx1, gy1)))

        return results

    def _cluster_centers(self, centers: list[float], tol: float) -> list[float]:
        """Merge nearby x-centers into representative column anchors."""
        if not centers:
            return []
        sorted_c = sorted(centers)
        clusters: list[list[float]] = [[sorted_c[0]]]
        for c in sorted_c[1:]:
            if c - clusters[-1][-1] <= tol:
                clusters[-1].append(c)
            else:
                clusters.append([c])
        return [sum(cl) / len(cl) for cl in clusters]

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

            metadata: dict[str, Any] = {
                "filename": filename,
                "block_type": block.block_type.value,
                "page_number": block.page_number,
                "headings": list(block.headings),
            }

            # Structured table fields — consumed by chunk_table_block (Step C)
            # to emit one summary chunk + N row chunks with column context.
            if block.block_type == _BlockType.TABLE and block.raw_cells:
                table = self._cells_to_table_dict(block.raw_cells, block.external_headers)
                if table:
                    metadata["table_columns"] = list(table["headers"])
                    metadata["table_rows"] = list(table["rows"])
                    metadata["table_label"] = block.headings[-1] if block.headings else None

            docs.append(Document(
                id=f"pdf_{uuid.uuid4().hex[:8]}",
                content=content,
                source_type="pdf",
                source_name=filename,
                metadata=metadata,
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
