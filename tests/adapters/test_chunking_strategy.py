"""Tests for TemporalMergeChunking Agno adapter."""

from __future__ import annotations

import pytest

pytest.importorskip("agno", reason="agno not installed")

from agno.knowledge.document.base import Document as AgnoDocument  # noqa: E402

from agno_plus.adapters.agno.chunking_strategy import TemporalMergeChunking  # noqa: E402


def _make_doc(content: str, content_id: str = "abc123") -> AgnoDocument:
    return AgnoDocument(id="doc-1", name="test.txt", content=content, content_id=content_id)


def test_chunk_returns_list():
    strategy = TemporalMergeChunking(max_tokens=50, overlap_tokens=5)
    doc = _make_doc("Hello world. " * 10)
    chunks = strategy.chunk(doc)
    assert isinstance(chunks, list)
    assert len(chunks) >= 1


def test_chunk_preserves_content_id():
    strategy = TemporalMergeChunking(max_tokens=50, overlap_tokens=5)
    doc = _make_doc("Some text. " * 20, content_id="my-content-id")
    chunks = strategy.chunk(doc)
    for chunk in chunks:
        assert chunk.content_id == "my-content-id"


def test_chunk_preserves_name():
    strategy = TemporalMergeChunking()
    doc = _make_doc("text", content_id="x")
    doc.name = "myfile.txt"
    chunks = strategy.chunk(doc)
    for chunk in chunks:
        assert chunk.name == "myfile.txt"


def test_chunk_empty_content_returns_one_chunk():
    strategy = TemporalMergeChunking()
    doc = _make_doc("")
    chunks = strategy.chunk(doc)
    assert len(chunks) == 1


def test_chunk_ids_are_unique():
    strategy = TemporalMergeChunking(max_tokens=20, overlap_tokens=2)
    doc = _make_doc("Word. " * 100)
    chunks = strategy.chunk(doc)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_meta_data_copied():
    strategy = TemporalMergeChunking()
    doc = _make_doc("Some content.")
    doc.meta_data = {"domain_id": "d1", "user_id": "u1"}
    chunks = strategy.chunk(doc)
    for chunk in chunks:
        assert chunk.meta_data.get("domain_id") == "d1"
        assert chunk.meta_data.get("user_id") == "u1"
