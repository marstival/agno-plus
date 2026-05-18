"""Internal spreadsheet models for the 3-layer parsing pipeline.

These are implementation details of SpreadsheetReader. External code works
with agno_plus.core.models.Document — the converter lives in spreadsheet.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Layer A — sparse grid
# ---------------------------------------------------------------------------


@dataclass
class CellValue:
    row: int        # 0-based
    col: int        # 0-based
    value: str
    merged: bool = False


@dataclass
class SheetGrid:
    sheet_name: str
    cells: list[CellValue]
    row_count: int
    col_count: int


# ---------------------------------------------------------------------------
# Layer B — layout blocks
# ---------------------------------------------------------------------------


class BlockType(str, Enum):
    TABLE = "table"
    KV_PAIR = "kv_pair"
    NOTE = "note"


@dataclass
class Block:
    block_type: BlockType
    sheet_name: str
    top_row: int        # inclusive, 0-based
    left_col: int
    bottom_row: int     # inclusive, 0-based
    right_col: int
    cells: list[CellValue]
    has_header: bool = False
    headers: list[str] = field(default_factory=list)
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Layer C — canonical records
# ---------------------------------------------------------------------------


@dataclass
class TableRow:
    sheet_name: str
    block_index: int
    row_index: int          # 0-based within the block's data rows
    fields: dict[str, str]
    confidence: float | None = None


@dataclass
class KVItem:
    sheet_name: str
    block_index: int
    key: str
    value: str
    confidence: float | None = None


@dataclass
class NoteItem:
    sheet_name: str
    block_index: int
    text: str
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Root parse result (internal)
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    filename: str
    sheet_grids: list[SheetGrid]
    blocks: list[Block]
    table_rows: list[TableRow]
    kv_items: list[KVItem]
    notes: list[NoteItem]
