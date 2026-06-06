"""Tests for chunking utilities and IngestionPipeline."""

from __future__ import annotations

import io
import csv

import pytest

from agno_plus.core.models import Document, JobState, JobStep, MemoryRecord
from agno_plus.core.pipeline.chunking import (
    chunk_prose_block,
    chunk_table_block,
    chunk_text,
    chunk_text_structured,
)
from agno_plus.core.pipeline.worker import IngestionPipeline, IngestionWorker
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.time_grounding.grounder import TemporalGrounder


# ---------------------------------------------------------------------------
# chunk_text — sliding window
# ---------------------------------------------------------------------------


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_short_stays_one():
    result = chunk_text("hello world", max_tokens=10)
    assert result == ["hello world"]


def test_chunk_text_splits_long():
    words = " ".join(f"word{i}" for i in range(50))
    result = chunk_text(words, max_tokens=20, overlap_tokens=5)
    assert len(result) > 1
    # Each chunk (except maybe the last) is at most max_tokens + overlap words
    for chunk in result[:-1]:
        assert len(chunk.split()) <= 25  # generous bound


def test_chunk_text_overlap_carries_words():
    words = " ".join(f"word{i}" for i in range(30))
    result = chunk_text(words, max_tokens=10, overlap_tokens=5)
    # Second chunk should start with some words from the first chunk
    assert len(result) >= 2
    last_of_first = result[0].split()[-5:]
    start_of_second = result[1].split()[:5]
    assert last_of_first == start_of_second


# ---------------------------------------------------------------------------
# chunk_text_structured — boundary-aware
# ---------------------------------------------------------------------------


def test_structured_empty():
    assert chunk_text_structured("") == []


def test_structured_single_paragraph():
    text = "This is a paragraph about something interesting that spans multiple words."
    result = chunk_text_structured(text, max_tokens=100)
    assert len(result) == 1
    assert "paragraph" in result[0]


def test_structured_headings_split_blocks():
    text = "## Section A\nContent about section A.\n\n## Section B\nContent about section B."
    result = chunk_text_structured(text, max_tokens=5)
    assert len(result) >= 2


def test_structured_markdown_table_stays_together():
    table = (
        "### Table (rows 1-5, cols A-C)\n"
        "| Name | Age | City |\n"
        "| --- | --- | --- |\n"
        "| Alice | 30 | NY |\n"
        "| Bob | 25 | LA |\n"
    )
    result = chunk_text_structured(table, max_tokens=200)
    # Should not split the table across chunks
    assert any("Alice" in chunk and "Bob" in chunk for chunk in result)


def test_structured_bullets_each_own_block():
    text = "- item one\n- item two\n- item three"
    result = chunk_text_structured(text, max_tokens=2)
    # Each bullet is a separate block; with max_tokens=2 they stay separate
    assert len(result) >= 2


def test_structured_with_similarity_fn_forces_split():
    def always_dissimilar(a: str, b: str) -> float:
        return 0.0  # never merge

    text = "paragraph one content here\n\nparagraph two content here"
    result = chunk_text_structured(
        text,
        max_tokens=200,
        similarity_fn=always_dissimilar,
        similarity_threshold=0.5,
    )
    assert len(result) >= 2


def test_structured_with_similarity_fn_forces_merge():
    def always_similar(a: str, b: str) -> float:
        return 1.0  # always merge

    text = "block one\n\nblock two\n\nblock three"
    result = chunk_text_structured(
        text,
        max_tokens=200,
        similarity_fn=always_similar,
        similarity_threshold=0.5,
    )
    # All blocks should merge into one (under token limit)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# IngestionPipeline
# ---------------------------------------------------------------------------


def make_csv_bytes(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


class FakeMemoryStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def upsert(self, content: str, metadata: dict) -> MemoryRecord:
        self.records.append((content, metadata))
        return MemoryRecord(id=f"r{len(self.records)}", content=content, metadata=metadata)

    def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
        return []

    def delete(self, record_id: str) -> None:
        pass


def make_pipeline(store: FakeMemoryStore) -> IngestionPipeline:
    return IngestionPipeline(
        readers={".csv": SpreadsheetReader(), ".xlsx": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )


def test_pipeline_protocol_compliance():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    assert isinstance(pipeline, IngestionWorker)


def test_pipeline_submit_returns_job_id():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    data = make_csv_bytes([
        ["Name", "Age", "City"],
        ["Alice", "30", "NY"],
        ["Bob", "25", "LA"],
        ["Carol", "35", "SF"],
    ])
    job_id = pipeline.submit(data, "test.csv", {})
    assert job_id.startswith("job_")


def test_pipeline_job_completes():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    data = make_csv_bytes([
        ["Name", "Age", "City"],
        ["Alice", "30", "NY"],
        ["Bob", "25", "LA"],
        ["Carol", "35", "SF"],
    ])
    job_id = pipeline.submit(data, "test.csv", {})
    status = pipeline.status(job_id)
    assert status.state == JobState.COMPLETED
    assert JobStep.READ in status.completed_steps
    assert JobStep.UPSERT in status.completed_steps


def test_pipeline_upserts_to_store():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    data = make_csv_bytes([
        ["Name", "Age", "City"],
        ["Alice", "30", "NY"],
        ["Bob", "25", "LA"],
        ["Carol", "35", "SF"],
    ])
    pipeline.submit(data, "test.csv", {"user_id": "u1"})
    assert len(store.records) >= 1
    # Every upserted record should carry the filename metadata
    for _, meta in store.records:
        assert meta.get("filename") == "test.csv"


def test_pipeline_propagates_source_document_metadata():
    """Per-Document metadata produced by the reader (block_type, page_number,
    headings, …) must reach every chunk upserted into the store. Without this
    propagation, retrieval results have no way to cite their source."""
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    data = make_csv_bytes([
        ["Date", "Item"],
        ["2026-05-01", "A"],
        ["2026-05-02", "B"],
    ])
    pipeline.submit(data, "items.csv", {"user_id": "u1"})
    assert len(store.records) >= 1
    # SpreadsheetReader sets source_type and block-level fields in Document.metadata;
    # the pipeline must merge them into the upserted chunk metadata.
    for _, meta in store.records:
        # submit-time fields preserved
        assert meta["user_id"] == "u1"
        assert meta["filename"] == "items.csv"
        # reader-emitted fields propagated
        assert "block_type" in meta or "sheet_name" in meta, (
            f"reader metadata did not reach chunk: {meta}"
        )


def test_pipeline_unknown_extension_fails():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    job_id = pipeline.submit(b"data", "file.pdf", {})
    status = pipeline.status(job_id)
    assert status.state == JobState.FAILED
    assert status.error is not None


def test_pipeline_status_unknown_job_raises():
    store = FakeMemoryStore()
    pipeline = make_pipeline(store)
    with pytest.raises(KeyError):
        pipeline.status("nonexistent_job")


# ---------------------------------------------------------------------------
# chunk_table_block — table-aware row-level chunking
# ---------------------------------------------------------------------------


def test_chunk_table_block_summary_plus_rows():
    chunks = chunk_table_block(
        columns=["Tier", "Price"],
        rows=[{"Tier": "Bronze", "Price": "100"}, {"Tier": "Gold", "Price": "200"}],
    )
    # One summary + N rows
    assert len(chunks) == 3
    assert "columns: Tier, Price" in chunks[0]
    assert "2 rows" in chunks[0]
    assert "Tier: Bronze" in chunks[1] and "Price: 100" in chunks[1]
    assert "Tier: Gold" in chunks[2]


def test_chunk_table_block_includes_breadcrumb_and_label():
    chunks = chunk_table_block(
        columns=["A"],
        rows=[{"A": "1"}],
        headings=["Section 3", "3.1 Pricing"],
        table_label="Pricing Tiers",
    )
    for c in chunks:
        assert "Section 3 > 3.1 Pricing" in c
        assert "Pricing Tiers" in c


def test_chunk_table_block_empty_returns_empty():
    assert chunk_table_block(columns=[], rows=[]) == []
    assert chunk_table_block(columns=["A"], rows=[]) == []


def test_chunk_table_block_singular_row_word():
    chunks = chunk_table_block(columns=["A"], rows=[{"A": "1"}])
    assert "1 row" in chunks[0] and "1 rows" not in chunks[0]


# ---------------------------------------------------------------------------
# chunk_prose_block — heading breadcrumb on prose
# ---------------------------------------------------------------------------


def test_chunk_prose_block_prepends_breadcrumb():
    chunks = chunk_prose_block("Some paragraph text.", headings=["Section 3", "3.1 Pricing"])
    assert chunks
    assert all(c.startswith("[Section 3 > 3.1 Pricing] ") for c in chunks)


def test_chunk_prose_block_no_headings_passes_through():
    chunks = chunk_prose_block("Some paragraph text.")
    assert chunks
    assert not any(c.startswith("[") for c in chunks)


def test_chunk_prose_block_skips_breadcrumb_when_chunk_is_heading():
    """A block whose content IS one of the headings (e.g. a single-line section
    title) shouldn't be wrapped as `[X] X` — it stays as just `X`."""
    chunks = chunk_prose_block("INVOICE", headings=["INVOICE"])
    assert chunks == ["INVOICE"]


# ---------------------------------------------------------------------------
# Pipeline dispatch by block_type
# ---------------------------------------------------------------------------


def test_pipeline_dispatches_table_block_to_row_chunks():
    """When a reader emits a Document with block_type='table' and table_rows
    in metadata, the pipeline must use chunk_table_block — producing one chunk
    per row, not one chunk per markdown table."""

    class _TableReader:
        def read(self, source, **kwargs):
            return [
                Document(
                    id="d1",
                    content="### Table (page 1)\n| Tier | Price |\n|---|---|\n| Bronze | 100 |\n| Gold | 200 |",
                    source_type="pdf",
                    source_name="x.pdf",
                    metadata={
                        "block_type": "table",
                        "page_number": 1,
                        "headings": ["3.1 Pricing"],
                        "table_label": "3.1 Pricing",
                        "table_columns": ["Tier", "Price"],
                        "table_rows": [
                            {"Tier": "Bronze", "Price": "100"},
                            {"Tier": "Gold", "Price": "200"},
                        ],
                    },
                )
            ]

    store = FakeMemoryStore()
    pipeline = IngestionPipeline(
        readers={".pdf": _TableReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    pipeline.submit(b"_", "x.pdf", {"user_id": "u1"})

    assert len(store.records) == 3  # summary + 2 rows
    summary, row1, row2 = store.records
    assert "columns: Tier, Price" in summary[0]
    assert "Tier: Bronze" in row1[0] and "Price: 100" in row1[0]
    assert "Tier: Gold" in row2[0]
    # Every chunk carries the source metadata
    for _, meta in store.records:
        assert meta["block_type"] == "table"
        assert meta["page_number"] == 1
        assert meta["table_label"] == "3.1 Pricing"
