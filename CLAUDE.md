# agno-plus — Claude Code Instructions

## What this project is

`agno-plus` is a reusable Python + React extension layer for [Agno](https://github.com/agno-agi/agno). It provides enhanced ingestion, episodic memory with temporal grounding, STT, OCR, a background pipeline, and UI components. It is **not** a vertical application — applications are built on top of it.

Full specification: `AGNO_EXTENSION.md` in this repo. Read it before making architectural decisions.

## Design principles (non-negotiable)

1. **Framework-agnostic core** — `agno_plus/core/` has zero framework imports. Agno/LangChain code lives only in `agno_plus/adapters/`.
2. **Own Document type** — `core/models.py` defines `Document`, `Chunk`, `MemoryRecord`. Adapters convert to/from framework types.
3. **No LLM calls during ingestion** — all pipeline steps are deterministic. LLM calls happen only inside the agent's reasoning loop.
4. **App-layer config only** — grounding mode, chunking strategy, backend selection are set at bootstrap, never at runtime per-message.

## Architecture

```
agno_plus/
  core/                  ← zero framework deps
    models.py            ← Document, Chunk, IngestionResult, MemoryRecord, JobStatus
    readers/
      base.py            ← Reader Protocol
      spreadsheet.py     ← 3-layer pipeline (grid → blocks → records)
      audio.py           ← Whisper STT
      image.py           ← OCR via vision LLM
    time_grounding/
      grounder.py        ← TemporalGrounder (EN / PT-BR / ES)
      episodic.py        ← EpisodicMemoryGrounder (wraps MemoryStore)
      models.py          ← GroundingMode, TimeGrounding
    pipeline/
      worker.py          ← IngestionWorker Protocol + job state machine
      chunking.py        ← semantic merge chunking
  adapters/
    agno/                ← thin wrappers: AgnoSpreadsheetReader, AgnoMemoryStore, …
    langchain/           ← thin wrappers: LangChainSpreadsheetLoader, …
    pgvector/            ← PgvectorMemoryStore
ui/
  src/components/
    UploadWidget/
    JobStatusWidget/
    KnowledgeBrowser/
examples/
  personal-aide-minimal/ ← end-to-end validation of the full stack
tests/
```

## Build order

Steps in sequence — each has a natural test boundary before moving to the next:

- [ ] 1. `core/models.py` — `Document`, `Chunk`, `IngestionResult`, `MemoryRecord`, `JobStatus`
- [ ] 2. `core/time_grounding/` — `TemporalGrounder`, `GroundingMode`, `EpisodicMemoryGrounder`
- [ ] 3. `core/readers/spreadsheet.py` — 3-layer pipeline (port from reference codebase)
- [ ] 4. `core/pipeline/` — `IngestionWorker` protocol, job state machine, chunking
- [ ] 5. `adapters/agno/` — thin wrappers for readers + memory store
- [ ] 6. `examples/personal-aide-minimal/` — end-to-end: ingest a spreadsheet, ask a question
- [ ] 7. `core/readers/audio.py` and `core/readers/image.py` — STT and OCR
- [ ] 8. `adapters/langchain/` — LangChain loader wrappers
- [ ] 9. `ui/components/` — UploadWidget, JobStatusWidget, KnowledgeBrowser

## Key design decisions already made

- **Time grounding for episodic memory** is wired to chat channels only, always `PERSONAL` mode, `reference_date=now()`. `EpisodicMemoryGrounder` wraps any `MemoryStore` and applies grounding automatically before upsert. This is not user-facing.
- **File ingestion grounding mode** is set per reader type at app bootstrap (receipt image → `PERSONAL`, PDF book → `DOCUMENT`, unknown → `AUTO`).
- **SpreadsheetReader** must use `openpyxl` with `read_only=False` and expand `ws.merged_cells.ranges` to propagate master cell values — Agno's native ExcelReader uses `read_only=True` and silently drops merged content.
- **GroundingMode.AUTO** uses sentence-level heuristic: first-person pronouns co-occurring with a relative time expression → normalize that sentence. No LLM call.
- **Agno is the primary adapter target.** LangChain is secondary. The framework-agnostic core means either can be added without touching core logic.

## Reference codebase

The personal assistant that informed this design lives at:
`/Users/stival/Projetos/personal-agentic-aide/`

Relevant source files to port from:
- `backend/app/services/spreadsheet/` — full 3-layer pipeline (Layer A/B/C)
- `backend/app/services/time_grounding_service.py` — multilingual temporal grounding
- `backend/app/core/constants.py` — spreadsheet thresholds and constants

Do not modify the reference repo. Read from it, port to agno-plus.

## Commands

```bash
# Install in editable mode (dev)
pip install -e ".[dev,agno]"

# Tests
pytest -q

# Lint / format
ruff check agno_plus/
ruff format agno_plus/
```

## Conventions

- Python 3.11+, type hints everywhere, `from __future__ import annotations`
- Dataclasses for models (not Pydantic) — keeps core dependency-free
- `Protocol` for all interfaces (not ABC) — structural subtyping, no forced inheritance
- No comments explaining what code does — only why when non-obvious
- UTC naive datetimes for storage (`datetime.now(timezone.utc).replace(tzinfo=None)`)
