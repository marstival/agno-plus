"""Phase 0 tests: SourceRef, TracingPort, TemporalGrounderDb."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from agno_plus.core.models import (
    DataRef,
    EpisodicRef,
    KnowledgeRef,
    SourceRef,
    WebRef,
)
from agno_plus.core.time_grounding.hook import TemporalGrounderDb
from agno_plus.core.tracing import TracingPort


# ---------------------------------------------------------------------------
# SourceRef
# ---------------------------------------------------------------------------


class TestSourceRef:
    def test_episodic_ref_is_source_ref(self) -> None:
        ref: SourceRef = EpisodicRef(
            memory_id="m1",
            event_at=datetime(2026, 5, 20),
            excerpt="I had lunch with João",
        )
        assert ref.source_type == "episodic"

    def test_knowledge_ref_is_source_ref(self) -> None:
        ref: SourceRef = KnowledgeRef(
            domain_id="d1",
            domain_name="Literature",
            document_name="Dom Casmurro.pdf",
            excerpt="Capitu olhou para o mar",
            score=0.87,
        )
        assert ref.source_type == "knowledge"

    def test_data_ref_is_source_ref(self) -> None:
        ref: SourceRef = DataRef(
            domain_id="d2",
            domain_name="Finance",
            table_name="financials_2024",
            sql_query="SELECT SUM(revenue) FROM financials_2024",
            row_count=1,
        )
        assert ref.source_type == "data"

    def test_web_ref_is_source_ref(self) -> None:
        ref: SourceRef = WebRef(
            url="https://example.com",
            title="Example",
            snippet="Some snippet",
        )
        assert ref.source_type == "web"

    def test_source_refs_are_dataclasses(self) -> None:
        for cls in (EpisodicRef, KnowledgeRef, DataRef, WebRef):
            assert dataclasses.is_dataclass(cls)

    def test_serialisable_to_dict(self) -> None:
        ref = KnowledgeRef(
            domain_id="d1", domain_name="Lit", document_name="book.pdf",
            excerpt="...", score=0.9,
        )
        d = dataclasses.asdict(ref)
        assert d["source_type"] == "knowledge"
        assert d["score"] == 0.9


# ---------------------------------------------------------------------------
# TracingPort structural check
# ---------------------------------------------------------------------------


class TestTracingPort:
    def test_concrete_class_satisfies_protocol(self) -> None:
        class DummyTracer:
            def start_run(self, user_id: str, input_text: str) -> str:
                return "run_1"

            def log_tool_call(self, run_id, step, tool_name, tool_args, tool_result=None, error=None):
                pass

            def log_retrieval(self, run_id, source_ref, score=0.0):
                pass

            def log_answer(self, run_id, answer_text, sources):
                pass

            def complete_run(self, run_id, intents, status="completed"):
                pass

        assert isinstance(DummyTracer(), TracingPort)

    def test_incomplete_class_does_not_satisfy_protocol(self) -> None:
        class IncompleteTracer:
            def start_run(self, user_id: str, input_text: str) -> str:
                return "x"
            # missing log_tool_call, log_retrieval, log_answer, complete_run

        assert not isinstance(IncompleteTracer(), TracingPort)


# ---------------------------------------------------------------------------
# TemporalGrounderDb
# ---------------------------------------------------------------------------


class _FakeMemory:
    """Duck-typed stand-in for agno.db.schemas.memory.UserMemory."""

    def __init__(self, text: str, topics: list[str] | None = None) -> None:
        self.memory = text
        self.topics = topics or []


class _FakeDb:
    """Minimal duck-typed BaseDb for testing."""

    def __init__(self) -> None:
        self.upserted: list[Any] = []

    def upsert_user_memory(self, memory: Any, deserialize: Any = True) -> Any:
        self.upserted.append(memory)
        return memory

    def upsert_memories(self, memories: list[Any], **kwargs: Any) -> list[Any]:
        self.upserted.extend(memories)
        return memories

    def get_user_memories(self, **kwargs: Any) -> list[Any]:
        return self.upserted


class TestTemporalGrounderDb:
    def test_delegates_non_overridden_methods(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        result = wrapped.get_user_memories()
        assert result == []

    def test_grounding_applied_on_upsert(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("I had lunch with João yesterday")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        # Yesterday's date should appear in the text
        assert "yesterday" in stored.memory.lower() or any(
            c.isdigit() for c in stored.memory
        )

    def test_event_at_topic_added(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("I met Bob yesterday")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        assert any(t.startswith("event_at:") for t in (stored.topics or []))

    def test_no_event_at_when_no_temporal_expression(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("Bob is my colleague")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        assert not any(t.startswith("event_at:") for t in (stored.topics or []))

    def test_batch_upsert_grounds_all(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        memories = [
            _FakeMemory("I had lunch yesterday"),
            _FakeMemory("I went to the gym last Monday"),
        ]
        wrapped.upsert_memories(memories)
        assert len(fake_db.upserted) == 2
        for stored in fake_db.upserted:
            assert any(t.startswith("event_at:") for t in (stored.topics or []))

    def test_existing_event_at_topic_replaced(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("I met Ana yesterday", topics=["event_at:2020-01-01"])
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        event_at_topics = [t for t in stored.topics if t.startswith("event_at:")]
        assert len(event_at_topics) == 1
        assert event_at_topics[0] != "event_at:2020-01-01"

    def test_inline_iso_date_populates_event_at(self) -> None:
        """Memories already containing an ISO date (e.g. produced by
        pre-grounding the user input — see ADR-0005) still get the topic."""
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("User bought groceries on 2026-06-04 for 45 EUR")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        assert "event_at:2026-06-04" in stored.topics

    def test_inline_iso_first_match_wins(self) -> None:
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("Trip from 2026-06-01 to 2026-06-08 covered Lisbon and Porto")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        assert "event_at:2026-06-01" in stored.topics

    def test_invalid_iso_date_rejected(self) -> None:
        """Regex matches don't bypass datetime validation (no event_at for
        impossible dates like 2024-13-45)."""
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("Reference 2024-13-45 mentioned in old logs")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        assert not any(t.startswith("event_at:") for t in (stored.topics or []))

    def test_relative_grounding_beats_inline_iso(self) -> None:
        """When the grounder rewrites a relative expression, its resolved date
        wins over any pre-existing inline ISO date in the same text."""
        fake_db = _FakeDb()
        wrapped = TemporalGrounderDb(db=fake_db)
        mem = _FakeMemory("Old note dated 2020-01-01: I met Bob yesterday")
        wrapped.upsert_user_memory(mem)
        stored = fake_db.upserted[0]
        event_at_topics = [t for t in stored.topics if t.startswith("event_at:")]
        assert len(event_at_topics) == 1
        assert event_at_topics[0] != "event_at:2020-01-01"
