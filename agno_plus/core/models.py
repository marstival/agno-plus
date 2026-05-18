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
