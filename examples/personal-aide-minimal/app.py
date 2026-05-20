"""Personal Aide — full-stack FastAPI backend for the agno-plus showcase.

Endpoints
---------
POST /ingest            multipart file → { job_id }
GET  /jobs/{job_id}     → JobStatus (polled by JobStatusWidget)
GET  /memories          → { records: MemoryRecord[] } (served to KnowledgeBrowser)
POST /chat              → { reply } (RAG over memory + OpenAI)

Run
---
    pip install -r requirements.txt
    cd examples/personal-aide-minimal
    PYTHONPATH=../.. uvicorn app:app --reload --port 8000

Set OPENAI_API_KEY before starting.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agno_plus.core.models import JobState, JobStatus, MemoryRecord
from agno_plus.core.pipeline.worker import IngestionPipeline
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder
from agno_plus.core.time_grounding.grounder import TemporalGrounder


# ---------------------------------------------------------------------------
# In-memory store (no vector DB needed for the demo)
# ---------------------------------------------------------------------------


class InMemoryStore:
    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def upsert(self, content: str, metadata: dict[str, Any]) -> MemoryRecord:
        event_at = metadata.get("event_at")
        record = MemoryRecord(
            id=f"r_{uuid.uuid4().hex[:8]}",
            content=content,
            metadata=metadata,
            event_at=event_at if isinstance(event_at, datetime) else None,
        )
        self.records.append(record)
        return record

    def search(self, query: str, user_id: str, **kwargs: Any) -> list[MemoryRecord]:
        q = query.lower()
        return [r for r in self.records if q in r.content.lower()]

    def delete(self, record_id: str) -> None:
        self.records = [r for r in self.records if r.id != record_id]


# ---------------------------------------------------------------------------
# Pipeline that runs in a background thread so /ingest returns immediately
# ---------------------------------------------------------------------------


class BackgroundIngestionPipeline(IngestionPipeline):
    """Override submit() to run _run() in a daemon thread."""

    def submit(self, source: bytes | str, filename: str, meta: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        self._jobs[job_id] = JobStatus(job_id=job_id, state=JobState.PENDING)
        threading.Thread(
            target=self._run, args=(job_id, source, filename, meta), daemon=True
        ).start()
        return job_id


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------


app = FastAPI(title="Personal Aide — agno-plus showcase")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = InMemoryStore()
grounder = TemporalGrounder()

pipeline = BackgroundIngestionPipeline(
    readers={
        ".csv": SpreadsheetReader(),
        ".xlsx": SpreadsheetReader(),
        ".xls": SpreadsheetReader(),
        ".tsv": SpreadsheetReader(),
    },
    memory_store=store,
    grounder=grounder,
)

episodic = EpisodicMemoryGrounder(store=store, grounder=grounder)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _serialize(vv) for k, vv in v.items()}
    if isinstance(v, list):
        return [_serialize(i) for i in v]
    return v


def _record_dict(r: MemoryRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "content": r.content,
        "metadata": _serialize(r.metadata),
        "event_at": r.event_at.isoformat() if r.event_at else None,
    }


def _status_dict(s: JobStatus) -> dict[str, Any]:
    return {
        "job_id": s.job_id,
        "state": s.state.value,
        "current_step": s.current_step.value if s.current_step else None,
        "completed_steps": [step.value for step in s.completed_steps],
        "error": s.error,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)) -> dict[str, str]:
    content = await file.read()
    filename = file.filename or "upload.csv"
    job_id = pipeline.submit(content, filename, {"source_name": filename, "source": "file"})
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return _status_dict(pipeline.status(job_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")


@app.get("/memories")
def list_memories(user_id: str = "demo_user", query: str = "") -> dict[str, Any]:
    if query.strip():
        records = store.search(query.strip(), user_id)
    else:
        records = list(store.records)
    return {"records": [_record_dict(r) for r in records]}


class ChatRequest(BaseModel):
    message: str
    user_id: str = "demo_user"


@app.post("/chat")
async def chat(body: ChatRequest) -> dict[str, str]:
    memories = store.search(body.message, body.user_id)
    episodic.store(body.message, user_id=body.user_id)

    context = "\n---\n".join(r.content[:400] for r in memories[:6])
    system = (
        "You are a helpful personal assistant with access to the user's memory.\n"
        "Answer based on the following context retrieved from memory:\n\n"
        f"{context or '(no relevant memories found)'}\n\n"
        "If the context is insufficient, say so and answer from general knowledge."
    )

    try:
        import openai  # optional dep; fail at call time, not import time

        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": body.message},
            ],
            max_tokens=600,
        )
        return {"reply": resp.choices[0].message.content or ""}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
