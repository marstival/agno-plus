"""IngestionWorker Protocol and in-memory pipeline implementation.

Job state machine:
    pending → processing → completed
                       ↘ failed
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from agno_plus.core.models import (
    Document,
    JobState,
    JobStatus,
    JobStep,
    MemoryStore,
)
from agno_plus.core.readers.base import Reader
from agno_plus.core.pipeline.chunking import chunk_text_structured
from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.models import GroundingMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IngestionWorker(Protocol):
    def submit(self, source: bytes | str, filename: str, meta: dict[str, Any]) -> str: ...
    def status(self, job_id: str) -> JobStatus: ...


# ---------------------------------------------------------------------------
# In-memory pipeline
# ---------------------------------------------------------------------------


class IngestionPipeline:
    """Synchronous in-memory ingestion pipeline.

    Runs all steps inline (no background threads). Suitable for examples
    and tests. Production apps should wrap this in async workers or Celery.
    """

    def __init__(
        self,
        readers: dict[str, Reader],
        memory_store: MemoryStore,
        grounder: TemporalGrounder,
        max_tokens: int = 400,
        overlap_tokens: int = 40,
    ) -> None:
        self._readers = readers            # extension → Reader instance
        self._store = memory_store
        self._grounder = grounder
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._jobs: dict[str, JobStatus] = {}

    # ------------------------------------------------------------------
    # IngestionWorker interface
    # ------------------------------------------------------------------

    def submit(self, source: bytes | str, filename: str, meta: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        status = JobStatus(job_id=job_id, state=JobState.PENDING)
        self._jobs[job_id] = status
        self._run(job_id, source, filename, meta)
        return job_id

    def status(self, job_id: str) -> JobStatus:
        if job_id not in self._jobs:
            raise KeyError(f"Unknown job: {job_id}")
        return self._jobs[job_id]

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    def _run(
        self, job_id: str, source: bytes | str, filename: str, meta: dict[str, Any]
    ) -> None:
        status = self._jobs[job_id]
        status.state = JobState.PROCESSING

        try:
            # Step 1: Read
            status.current_step = JobStep.READ
            documents = self._step_read(source, filename)
            status.completed_steps.append(JobStep.READ)

            # Step 2: Ground
            status.current_step = JobStep.GROUND
            grounding_mode = GroundingMode(meta.get("grounding_mode", GroundingMode.AUTO))
            documents = self._step_ground(documents, grounding_mode)
            status.completed_steps.append(JobStep.GROUND)

            # Step 3: Chunk
            status.current_step = JobStep.CHUNK
            chunks_text = self._step_chunk(documents)
            status.completed_steps.append(JobStep.CHUNK)

            # Step 4–5: Embed + Upsert (delegated to MemoryStore)
            status.current_step = JobStep.EMBED
            status.completed_steps.append(JobStep.EMBED)

            status.current_step = JobStep.UPSERT
            for chunk_content in chunks_text:
                self._store.upsert(
                    content=chunk_content,
                    metadata={**meta, "filename": filename},
                )
            status.completed_steps.append(JobStep.UPSERT)

            status.state = JobState.COMPLETED
            status.current_step = None

        except Exception as exc:
            logger.exception("Ingestion job %s failed", job_id)
            status.state = JobState.FAILED
            status.error = str(exc)
            status.current_step = None
        finally:
            status.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def _step_read(self, source: bytes | str, filename: str) -> list[Document]:
        from pathlib import Path

        ext = Path(filename).suffix.lower()
        reader = self._readers.get(ext)
        if reader is None:
            raise ValueError(f"No reader registered for extension '{ext}'")
        return reader.read(source, filename=filename)

    def _step_ground(
        self, documents: list[Document], mode: GroundingMode
    ) -> list[Document]:
        if mode == GroundingMode.DOCUMENT:
            return documents
        ref = datetime.now(timezone.utc).replace(tzinfo=None)
        for doc in documents:
            grounded, groundings = self._grounder.ground(doc.content, mode, ref)
            doc.content = grounded
            if groundings:
                doc.metadata["event_at"] = groundings[0].resolved_date
        return documents

    def _step_chunk(self, documents: list[Document]) -> list[str]:
        chunks: list[str] = []
        for doc in documents:
            chunks.extend(
                chunk_text_structured(
                    doc.content,
                    max_tokens=self._max_tokens,
                    overlap_tokens=self._overlap_tokens,
                )
                or [doc.content]  # never produce empty output for non-empty doc
            )
        return chunks
