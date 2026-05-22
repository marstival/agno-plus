"""Core domain models — zero framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Document-level models
# ---------------------------------------------------------------------------


@dataclass
class Document:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = ""   # "spreadsheet" | "audio" | "image" | "text"
    source_name: str = ""   # original filename


@dataclass
class Chunk:
    id: str
    document_id: str
    content: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionResult:
    job_id: str
    documents: list[Document] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    status: str = "pending"
    error: str | None = None


# ---------------------------------------------------------------------------
# Memory models
# ---------------------------------------------------------------------------


@dataclass
class MemoryRecord:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    event_at: datetime | None = None


# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------


class JobStep(str, Enum):
    READ = "read"
    GROUND = "ground"
    CHUNK = "chunk"
    EMBED = "embed"
    UPSERT = "upsert"


class JobState(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class JobStatus:
    job_id: str
    state: JobState = JobState.PENDING
    current_step: JobStep | None = None
    completed_steps: list[JobStep] = field(default_factory=list)
    error: str | None = None
    extraction_payload: list[dict] | None = None  # documents from read step
    chunks_count: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MemoryStore port (structural Protocol — no forced inheritance)
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStore(Protocol):
    def upsert(self, content: str, metadata: dict[str, Any]) -> MemoryRecord: ...
    def search(self, query: str, user_id: str, **kwargs: Any) -> list[MemoryRecord]: ...
    def delete(self, record_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Typed source references (produced by sub-agents, consumed by chat UI)
# ---------------------------------------------------------------------------


@dataclass
class EpisodicRef:
    """Citation from episodic memory recall."""
    memory_id: str
    event_at: datetime | None      # grounded event date, None if not temporal
    excerpt: str                   # first 300 chars of the memory text
    source_type: str = "episodic"


@dataclass
class KnowledgeRef:
    """Citation from a semantic knowledge domain."""
    domain_id: str
    domain_name: str
    document_name: str
    excerpt: str                   # chunk text preview
    score: float = 0.0
    source_type: str = "knowledge"


@dataclass
class DataRef:
    """Citation from a structured domain SQL query."""
    domain_id: str
    domain_name: str
    table_name: str
    sql_query: str
    row_count: int = 0
    source_type: str = "data"


@dataclass
class WebRef:
    """Citation from a web search result."""
    url: str
    title: str
    snippet: str
    source_type: str = "web"


# Union type for all source reference variants
SourceRef = EpisodicRef | KnowledgeRef | DataRef | WebRef
