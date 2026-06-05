"""Standalone CLI demo of the agno-plus core ingestion pipeline.

This file is intentionally independent of the FastAPI app — it runs with a
toy `InMemoryStore` so you can see the pipeline + temporal grounding in
action with no database, no LLM key, and no Docker.

Run from the agno-plus repo root:

    python examples/personal-aide-minimal/agent.py

For the full assistant (Agno Agent + RAG + memory + tracing) use the
FastAPI app:

    docker compose up -d
    open http://localhost:5173
"""

from __future__ import annotations

import csv
import io
import uuid

from agno_plus.core.models import MemoryRecord
from agno_plus.core.pipeline.worker import IngestionPipeline
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder
from agno_plus.core.time_grounding.grounder import TemporalGrounder


class InMemoryStore:
    """Toy MemoryStore — keyword search over a Python list."""

    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def upsert(self, content: str, metadata: dict) -> MemoryRecord:
        record = MemoryRecord(
            id=f"r_{uuid.uuid4().hex[:6]}",
            content=content,
            metadata=metadata,
        )
        self.records.append(record)
        return record

    def search(self, query: str, user_id: str, **_: object) -> list[MemoryRecord]:
        q = query.lower()
        return [r for r in self.records if q in r.content.lower()]

    def delete(self, record_id: str) -> None:
        self.records = [r for r in self.records if r.id != record_id]


def _sample_csv() -> bytes:
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


def main() -> None:
    store = InMemoryStore()
    grounder = TemporalGrounder()
    pipeline = IngestionPipeline(
        readers={".csv": SpreadsheetReader()},
        memory_store=store,
        grounder=grounder,
    )

    print("\n== Ingestion pipeline (ADR-0007) ==")
    job_id = pipeline.submit(_sample_csv(), "expenses.csv", {"grounding_mode": "document"})
    status = pipeline.status(job_id)
    print(f"  job        : {job_id}")
    print(f"  state      : {status.state.value}")
    print(f"  steps      : {[s.value for s in status.completed_steps]}")
    print(f"  chunks     : {status.chunks_count}")
    print(f"  records    : {len(store.records)}")

    print("\n== Episodic memory grounding (ADR-0005) ==")
    episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)
    episodic.store("I spent a lot at the supermarket yesterday", user_id="user1")
    grounded = store.records[-1]
    print(f"  content    : {grounded.content!r}")
    print(f"  event_at   : {grounded.metadata.get('event_at')}")

    print("\n== Keyword search ==")
    results = store.search("food", user_id="user1")
    print(f"  matches    : {len(results)}")
    for r in results[:3]:
        print(f"    - {r.content[:80]}")


if __name__ == "__main__":
    main()
