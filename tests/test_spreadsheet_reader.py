"""Tests for the 3-layer SpreadsheetReader pipeline."""

from __future__ import annotations

import csv
import io

import pytest

from agno_plus.core.models import Document
from agno_plus.core.readers.spreadsheet import SpreadsheetReader, _col_letter

reader = SpreadsheetReader()


# ---------------------------------------------------------------------------
# Helpers to build in-memory files without filesystem
# ---------------------------------------------------------------------------


def make_csv(rows: list[list[str]], delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter)
    writer.writerows(rows)
    return buf.getvalue().encode()


def make_xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    """Build a minimal .xlsx in memory with openpyxl."""
    import openpyxl

    wb = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# is_supported
# ---------------------------------------------------------------------------


def test_is_supported_xlsx():
    assert reader.is_supported("data.xlsx")


def test_is_supported_csv():
    assert reader.is_supported("export.csv")


def test_not_supported_pdf():
    assert not reader.is_supported("document.pdf")


# ---------------------------------------------------------------------------
# CSV: basic table detection
# ---------------------------------------------------------------------------


def test_csv_table_returns_documents():
    data = make_csv([
        ["Name", "Age", "City"],
        ["Alice", "30", "NY"],
        ["Bob", "25", "LA"],
        ["Carol", "35", "SF"],
    ])
    docs = reader.read(data, filename="test.csv")
    assert len(docs) >= 1
    assert all(isinstance(d, Document) for d in docs)


def test_csv_table_content_has_markdown_table():
    data = make_csv([
        ["Name", "Age", "City"],
        ["Alice", "30", "NY"],
        ["Bob", "25", "LA"],
        ["Carol", "35", "SF"],
    ])
    docs = reader.read(data, filename="test.csv")
    assert len(docs) == 1
    content = docs[0].content
    assert "| Name |" in content or "Name" in content
    assert "Alice" in content


def test_csv_metadata_block_type():
    data = make_csv([
        ["Product", "Price", "Stock"],
        ["Widget", "9.99", "100"],
        ["Gadget", "19.99", "50"],
        ["Doohickey", "4.99", "200"],
    ])
    docs = reader.read(data, filename="inventory.csv")
    assert docs[0].metadata["block_type"] == "table"
    assert docs[0].source_type == "spreadsheet"
    assert docs[0].source_name == "inventory.csv"


def test_csv_tsv_delimiter():
    data = b"Name\tAge\tCity\nAlice\t30\tNY\nBob\t25\tLA\nCarol\t35\tSF\n"
    docs = reader.read(data, filename="test.tsv")
    assert len(docs) >= 1
    assert "Alice" in docs[0].content


# ---------------------------------------------------------------------------
# CSV: KV pair detection
# ---------------------------------------------------------------------------


def test_csv_kv_pair():
    data = make_csv([
        ["Name", "Alice"],
        ["Age", "30"],
        ["City", "New York"],
        ["Email", "alice@example.com"],
    ])
    docs = reader.read(data, filename="profile.csv")
    assert len(docs) == 1
    content = docs[0].content
    assert docs[0].metadata["block_type"] == "kv_pair"
    assert "Name" in content and "Alice" in content
    assert "Age" in content and "30" in content


# ---------------------------------------------------------------------------
# CSV: note block (sparse/irregular data)
# ---------------------------------------------------------------------------


def test_csv_note_block():
    data = make_csv([
        ["This is a note about the dataset"],
    ])
    docs = reader.read(data, filename="note.csv")
    assert len(docs) == 1
    assert docs[0].metadata["block_type"] == "note"
    assert "note" in docs[0].content.lower() or "dataset" in docs[0].content


# ---------------------------------------------------------------------------
# CSV: multiple blocks detected
# ---------------------------------------------------------------------------


def test_csv_multiple_blocks():
    # Two separate tables with a gap
    rows = [
        ["A", "B", "C"],
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        ["", "", ""],
        ["", "", ""],
        ["X", "Y", "Z"],
        ["10", "20", "30"],
        ["40", "50", "60"],
        ["70", "80", "90"],
    ]
    data = make_csv(rows)
    docs = reader.read(data, filename="multi.csv")
    assert len(docs) >= 2


# ---------------------------------------------------------------------------
# Reader Protocol compliance
# ---------------------------------------------------------------------------


def test_reader_protocol_compliance():
    from agno_plus.core.readers.base import Reader

    assert isinstance(reader, Reader)


# ---------------------------------------------------------------------------
# XLSX: basic table
# ---------------------------------------------------------------------------


def test_xlsx_table():
    data = make_xlsx({
        "Sales": [
            ["Month", "Revenue", "Units"],
            ["Jan", "10000", "100"],
            ["Feb", "12000", "120"],
            ["Mar", "11000", "110"],
        ]
    })
    docs = reader.read(data, filename="sales.xlsx")
    assert len(docs) >= 1
    assert "Jan" in docs[0].content


def test_xlsx_metadata():
    data = make_xlsx({
        "Data": [
            ["Key", "Value"],
            ["Name", "Test"],
            ["Date", "2026-01-01"],
            ["Amount", "100.00"],
        ]
    })
    docs = reader.read(data, filename="data.xlsx")
    assert docs[0].metadata["sheet_name"] == "Data"
    assert docs[0].source_name == "data.xlsx"


def test_xlsx_multi_sheet():
    data = make_xlsx({
        "Sheet1": [
            ["A", "B", "C"],
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
        ],
        "Sheet2": [
            ["X", "Y", "Z"],
            ["10", "20", "30"],
            ["40", "50", "60"],
            ["70", "80", "90"],
        ],
    })
    docs = reader.read(data, filename="multi.xlsx")
    sheet_names = {d.metadata["sheet_name"] for d in docs}
    assert "Sheet1" in sheet_names
    assert "Sheet2" in sheet_names


# ---------------------------------------------------------------------------
# Document IDs are unique
# ---------------------------------------------------------------------------


def test_document_ids_unique():
    data = make_csv([
        ["A", "B", "C"],
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
    ])
    docs1 = reader.read(data, filename="a.csv")
    docs2 = reader.read(data, filename="a.csv")
    # IDs must be unique across calls (random uuid suffix)
    ids1 = {d.id for d in docs1}
    ids2 = {d.id for d in docs2}
    assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# Column letter helper
# ---------------------------------------------------------------------------


def test_col_letter_basic():
    assert _col_letter(0) == "A"
    assert _col_letter(25) == "Z"
    assert _col_letter(26) == "AA"
    assert _col_letter(27) == "AB"
    assert _col_letter(51) == "AZ"
    assert _col_letter(52) == "BA"


# ---------------------------------------------------------------------------
# Unsupported extension
# ---------------------------------------------------------------------------


def test_unsupported_extension_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        reader.read(b"data", filename="file.pdf")
