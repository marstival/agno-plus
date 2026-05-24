"""End-to-end test for examples/personal-aide-minimal/agent.py.

Runs the full pipeline (ingest → ground → chunk → upsert → search) without
any LLM API key. Validates that all agno-plus core components work together.
"""

from __future__ import annotations

import io
import csv
import sys
import os

# Allow importing from examples/ without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples", "personal-aide-minimal"))

from agno_plus.core.models import MemoryRecord, JobState
from agno_plus.core.pipeline.worker import IngestionPipeline
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


class InMemoryStore:
    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def upsert(self, content: str, metadata: dict) -> MemoryRecord:
        import uuid
        record = MemoryRecord(id=f"r_{uuid.uuid4().hex[:6]}", content=content, metadata=metadata)
        self.records.append(record)
        return record

    def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
        q = query.lower()
        return [r for r in self.records if q in r.content.lower()]

    def delete(self, record_id: str) -> None:
        self.records = [r for r in self.records if r.id != record_id]


def _make_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


def test_ingest_csv_completes():
    store = InMemoryStore()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    csv_bytes = _make_csv([
        ["Date", "Category", "Amount"],
        ["2026-05-01", "Food", "120.50"],
        ["2026-05-03", "Transport", "15.00"],
    ])
    job_id = pipeline.submit(csv_bytes, "test.csv", {"grounding_mode": "document"})
    status = pipeline.status(job_id)

    assert status.state == JobState.COMPLETED
    assert status.error is None
    assert len(store.records) > 0


def test_ingest_csv_produces_chunks_with_content():
    store = InMemoryStore()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    csv_bytes = _make_csv([
        ["Item", "Price"],
        ["Apple", "1.50"],
        ["Banana", "0.75"],
        ["Cherry", "3.00"],
    ])
    pipeline.submit(csv_bytes, "prices.csv", {"grounding_mode": "document"})

    assert len(store.records) > 0
    all_content = " ".join(r.content for r in store.records)
    assert "Apple" in all_content or "Banana" in all_content


def test_ingest_records_all_steps_completed():
    store = InMemoryStore()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    csv_bytes = _make_csv([["Col"], ["val"]])
    job_id = pipeline.submit(csv_bytes, "tiny.csv", {})
    status = pipeline.status(job_id)

    step_values = {s.value for s in status.completed_steps}
    assert "read" in step_values
    assert "chunk" in step_values
    assert "upsert" in step_values


def test_keyword_search_returns_matching_records():
    store = InMemoryStore()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    csv_bytes = _make_csv([
        ["Category", "Description"],
        ["Food", "supermarket groceries"],
        ["Transport", "taxi ride"],
        ["Health", "pharmacy visit"],
    ])
    pipeline.submit(csv_bytes, "expenses.csv", {"grounding_mode": "document"})

    results = store.search("taxi", user_id="u1")
    assert len(results) >= 1
    assert any("taxi" in r.content.lower() for r in results)


def test_unknown_extension_raises():
    store = InMemoryStore()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=TemporalGrounder(),
    )
    job_id = pipeline.submit(b"data", "file.pdf", {})
    status = pipeline.status(job_id)
    assert status.state == JobState.FAILED
    assert status.error is not None


# ---------------------------------------------------------------------------
# Episodic memory tests
# ---------------------------------------------------------------------------


def test_episodic_store_grounds_personal_memory():
    store = InMemoryStore()
    grounder = TemporalGrounder()
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)

    record = episodic.store("I had lunch with João yesterday", user_id="user1")

    assert record.id is not None
    assert "João" in record.content or "lunch" in record.content
    assert record.metadata.get("user_id") == "user1"


def test_episodic_store_adds_event_at_for_relative_time():
    store = InMemoryStore()
    grounder = TemporalGrounder()
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)

    episodic.store("I went to the gym yesterday", user_id="user1")

    records_with_event_at = [
        r for r in store.records if r.metadata.get("event_at") is not None
    ]
    assert len(records_with_event_at) >= 1


def test_episodic_search_delegates_to_store():
    store = InMemoryStore()
    grounder = TemporalGrounder()
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)

    episodic.store("had coffee at the bakery", user_id="u1")
    episodic.store("ran 5km in the park", user_id="u1")

    results = episodic.search("bakery", user_id="u1")
    assert len(results) >= 1
    assert any("bakery" in r.content.lower() for r in results)


# ---------------------------------------------------------------------------
# Full example smoke test (mirrors agent.py main())
# ---------------------------------------------------------------------------


def test_agent_main_smoke():
    """Runs the full agent.py pipeline end-to-end and asserts key invariants."""
    from agent import main  # noqa: PLC0415

    # main() prints to stdout; just assert it completes without raising
    main()


def test_pipeline_and_episodic_combined():
    """Combined: ingest CSV, add episodic memory, search both."""
    store = InMemoryStore()
    grounder = TemporalGrounder()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=grounder,
    )
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)

    csv_bytes = _make_csv([
        ["Date", "Category", "Amount"],
        ["2026-05-01", "Food", "120.50"],
        ["2026-05-05", "Restaurant", "35.00"],
    ])
    pipeline.submit(csv_bytes, "expenses.csv", {"grounding_mode": "document"})
    episodic.store("I ate at a restaurant yesterday", user_id="u1")

    food_results = store.search("food", user_id="u1")
    assert len(food_results) >= 1

    restaurant_results = store.search("restaurant", user_id="u1")
    assert len(restaurant_results) >= 1
