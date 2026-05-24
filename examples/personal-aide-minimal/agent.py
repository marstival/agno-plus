"""Minimal end-to-end example: ingest a spreadsheet, search episodic memory.

Run from the repo root:
    python examples/personal-aide-minimal/agent.py

Requires only the core extras (no LLM API key needed):
    pip install agno-plus[agno]
"""

from __future__ import annotations

import io
import os
import csv

from agno_plus.core.pipeline.worker import IngestionPipeline
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder
from agno_plus.core.models import MemoryRecord


# ---------------------------------------------------------------------------
# Minimal in-memory MemoryStore for demonstration (no vector DB needed)
# ---------------------------------------------------------------------------


class InMemoryStore:
    """Toy store — holds records in a list; search is keyword-only."""

    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def upsert(self, content: str, metadata: dict) -> MemoryRecord:
        import uuid
        record = MemoryRecord(
            id=f"r_{uuid.uuid4().hex[:6]}",
            content=content,
            metadata=metadata,
        )
        self.records.append(record)
        return record

    def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]:
        query_lower = query.lower()
        return [r for r in self.records if query_lower in r.content.lower()]

    def delete(self, record_id: str) -> None:
        self.records = [r for r in self.records if r.id != record_id]


# ---------------------------------------------------------------------------
# Build a sample spreadsheet in memory
# ---------------------------------------------------------------------------


def make_sample_spreadsheet() -> bytes:
    rows = [
        ["Date", "Category", "Description", "Amount"],
        ["2026-05-01", "Food", "Supermarket", "120.50"],
        ["2026-05-03", "Transport", "Uber", "15.00"],
        ["2026-05-05", "Food", "Restaurant lunch", "35.00"],
        ["2026-05-10", "Health", "Pharmacy", "45.00"],
        ["2026-05-15", "Food", "Bakery", "12.00"],
    ]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    store = InMemoryStore()
    grounder = TemporalGrounder()

    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=grounder,
    )

    print("Ingesting sample expenses spreadsheet...")
    spreadsheet_bytes = make_sample_spreadsheet()
    job_id = pipeline.submit(spreadsheet_bytes, "expenses.csv", {"grounding_mode": "document"})
    status = pipeline.status(job_id)
    print(f"  Job {job_id}: {status.state.value}")
    print(f"  Completed steps: {[s.value for s in status.completed_steps]}")
    print(f"  Records in store: {len(store.records)}")
    print()

    # Simulate episodic memory (chat message about an expense)
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)
    episodic.store("I spent a lot at the supermarket yesterday", user_id="user1")
    print("Stored episodic memory (grounded):")
    for r in store.records[-1:]:
        print(f"  content: {r.content!r}")
        print(f"  event_at: {r.metadata.get('event_at')}")
    print()

    # Simple keyword search
    results = store.search("food", user_id="user1")
    print(f"Search 'food' → {len(results)} result(s):")
    for r in results[:3]:
        print(f"  {r.content[:80]!r}")


if __name__ == "__main__":
    main()
