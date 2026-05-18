"""Tests for core domain models."""

from __future__ import annotations

from datetime import datetime

import pytest

from agno_plus.core.models import (
    Chunk,
    Document,
    IngestionResult,
    JobState,
    JobStatus,
    JobStep,
    MemoryRecord,
    MemoryStore,
)


def test_document_defaults():
    doc = Document(id="d1", content="hello")
    assert doc.source_type == ""
    assert doc.source_name == ""
    assert doc.metadata == {}


def test_document_with_metadata():
    doc = Document(id="d2", content="text", metadata={"key": "val"}, source_type="spreadsheet")
    assert doc.metadata["key"] == "val"
    assert doc.source_type == "spreadsheet"


def test_chunk_fields():
    chunk = Chunk(id="c1", document_id="d1", content="chunk text", chunk_index=0)
    assert chunk.chunk_index == 0
    assert chunk.metadata == {}


def test_ingestion_result_defaults():
    result = IngestionResult(job_id="j1")
    assert result.status == "pending"
    assert result.documents == []
    assert result.chunks == []
    assert result.error is None


def test_memory_record_optional_event_at():
    record = MemoryRecord(id="m1", content="bought groceries")
    assert record.event_at is None


def test_memory_record_with_event_at():
    dt = datetime(2026, 5, 18)
    record = MemoryRecord(id="m2", content="went to gym", event_at=dt)
    assert record.event_at == dt


def test_job_status_initial_state():
    status = JobStatus(job_id="j1")
    assert status.state == JobState.PENDING
    assert status.current_step is None
    assert status.completed_steps == []
    assert status.error is None


def test_job_status_transition():
    status = JobStatus(job_id="j1", state=JobState.PROCESSING, current_step=JobStep.READ)
    assert status.state == JobState.PROCESSING
    assert status.current_step == JobStep.READ


def test_job_step_values():
    assert JobStep.READ == "read"
    assert JobStep.EMBED == "embed"
    assert JobStep.UPSERT == "upsert"


def test_job_state_values():
    assert JobState.PENDING == "pending"
    assert JobState.FAILED == "failed"


def test_memory_store_protocol_structural():
    """Any class with the right methods satisfies MemoryStore without inheriting."""

    class InMemoryStore:
        def upsert(self, content: str, metadata: dict) -> MemoryRecord:
            return MemoryRecord(id="x", content=content, metadata=metadata)

        def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
            return []

        def delete(self, record_id: str) -> None:
            pass

    store = InMemoryStore()
    assert isinstance(store, MemoryStore)
