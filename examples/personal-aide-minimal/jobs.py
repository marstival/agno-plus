"""In-memory job tracker for the minimal demo.

A production app would back this with the DB per agno-plus guidance G-0002.
Here we keep it in-process so the example stays runnable without extra tables.

The tracker mirrors the agno-plus IngestionPipeline JobStatus shape so the
frontend's step bar can read the same fields regardless of whether the
ingestion path went through the pipeline or through a custom flow (the
structured CSV → SQL path).
"""

from __future__ import annotations

import uuid
from typing import Any

from agno_plus.core.models import JobState, JobStep

_jobs: dict[str, dict[str, Any]] = {}


def new_job() -> str:
    jid = f"job_{uuid.uuid4().hex[:8]}"
    _jobs[jid] = {
        "state": JobState.PENDING.value,
        "current_step": None,
        "completed_steps": [],
        "error": None,
    }
    return jid


def set_step(jid: str, step: JobStep | str) -> None:
    job = _jobs.get(jid)
    if not job:
        return
    job["state"] = JobState.PROCESSING.value
    if job["current_step"]:
        job["completed_steps"].append(job["current_step"])
    job["current_step"] = step.value if isinstance(step, JobStep) else step


def finish(jid: str, *, error: str | None = None) -> None:
    job = _jobs.get(jid)
    if not job:
        return
    if error:
        job["state"] = JobState.FAILED.value
        job["error"] = error
    else:
        if job["current_step"]:
            job["completed_steps"].append(job["current_step"])
        job["state"] = JobState.COMPLETED.value
    job["current_step"] = None


def get(jid: str) -> dict[str, Any] | None:
    return _jobs.get(jid)
