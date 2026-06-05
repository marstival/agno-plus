# G-0002 — Async ingest with 202 + poll, persistent job state

**Status:** Recommended for consumer applications

## Guidance

`IngestionPipeline.submit()` runs synchronously inside the reference implementation (ADR-0007). Production HTTP routes should not block on it.

Recommended pattern:

1. **`POST /ingest`** writes the raw file (via `StorageBackend`), inserts a row in the application's `ingested_files` table with `state="pending"`, dispatches the pipeline run to a worker (`ThreadPoolExecutor`, Celery, RQ, or asyncio), and returns **202 Accepted** with the `job_id`.
2. **The worker** runs `pipeline.submit(...)`, reads `pipeline.status(job_id)` after each step (or after completion), and writes two DB transitions: `pending → processing` at start, `processing → completed | failed` at end. Both transitions happen in the same transaction as the related `ingested_files` update — no half-states visible.
3. **`GET /ingest/jobs/{job_id}`** reads from the DB, not from `pipeline._jobs`. The DB is the source of truth across backend restarts.
4. **The frontend** polls every ~3 seconds (with a max-duration cap such as 3 minutes) and renders `current_step`/`completed_steps` as a step bar.

A `sync=true` form field bypasses the async path for tests, CLI scripts, and the minimal example.

## Why

File ingestion can run for minutes (audio transcription, OCR). Blocking the HTTP connection wastes a connection slot, leaves the client with no progress signal, and loses the job if the server restarts mid-flight. The 202 + DB-persisted-state pattern survives restarts and gives the client visibility without coupling to in-process state.

Two DB transitions (not five) match the user-relevant states. `read → ground → chunk → embed → upsert` is rendered from `JobStatus.completed_steps` in memory; only `pending`, `processing`, `completed`, and `failed` need to survive a restart.

## Apply when

- Wrapping `IngestionPipeline` in any HTTP route used by real users.
- Building a queue-driven worker (Celery, RQ).

## Apply if not

- A CLI that runs to completion (use `sync=true` or just call `pipeline.submit` directly).
- A test suite that mocks the pipeline.

## Related ADRs

- agno-plus ADR-0007 (IngestionPipeline contract).
- agentic-aide ADR-0014 (ingestion durability — 202 + poll pattern).
