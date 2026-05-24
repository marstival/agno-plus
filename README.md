# agno-plus

Reusable extension layer for [Agno](https://github.com/agno-agi/agno) with enhanced ingestion, episodic memory, and UI capabilities.

## Capabilities

- **SpreadsheetReader** — layout-aware Excel/CSV ingestion with merged cell expansion and block detection (TABLE / KV_PAIR / NOTE)
- **AudioReader** — STT via faster-whisper (local) or OpenAI Whisper API
- **ImageReader** — OCR via vision LLM (GPT-4o / Ollama llava)
- **TextReader / PdfReader** — plain text and PDF ingestion
- **TemporalGrounder** — multilingual (EN / PT-BR / ES) relative date normalization
- **EpisodicMemoryGrounder** — automatic temporal grounding for chat-originated memories
- **IngestionPipeline** — background worker with job state tracking (read → ground → chunk → embed → upsert)
- **SourceRef types** — `EpisodicRef`, `KnowledgeRef`, `DataRef`, `WebRef` — typed citations for agent answers
- **TracingPort** — `PgTracer` (DB lineage) and `LangfuseTracer` (OTLP) adapters
- **UI components** — `UploadWidget`, `JobStatusWidget`, `KnowledgeBrowser` (React / TypeScript)

## Adapter support

| Adapter | Status | What it provides |
|---|---|---|
| Agno (primary) | implemented | `AgnoSpreadsheetReader`, `AgnoAudioReader`, `AgnoImageReader`, `AgnoMemoryStore` |
| LangChain (secondary) | implemented | `LangChainSpreadsheetLoader`, `LangChainAudioLoader`, `LangChainImageLoader` |
| pgvector | implemented | `PgTracer` — writes DB lineage to `trace_*` tables |
| Langfuse | implemented | `LangfuseTracer` — OTLP span exporter |

## Design

Framework-agnostic core (`agno_plus/core/`) with zero framework dependencies. Adapters for Agno and LangChain live in `agno_plus/adapters/`. Full specification: `AGNO_EXTENSION.md`.

```
agno_plus/
  core/
    models.py              ← Document, Chunk, IngestionResult, MemoryRecord, JobStatus, SourceRef types
    tracing.py             ← TracingPort protocol
    readers/               ← base, spreadsheet, audio, image, text
    time_grounding/        ← TemporalGrounder, EpisodicMemoryGrounder, GroundingMode
    pipeline/              ← IngestionPipeline, IngestionWorker, chunking
  adapters/
    agno/                  ← AgnoSpreadsheetReader, AgnoAudioReader, AgnoImageReader, AgnoMemoryStore
    langchain/             ← LangChainSpreadsheetLoader, LangChainAudioLoader, LangChainImageLoader
    pgvector/              ← PgTracer
    langfuse/              ← LangfuseTracer
ui/
  src/components/
    UploadWidget/          ← file upload with drag-and-drop, progress feedback
    JobStatusWidget/       ← polls /ingest/jobs/:id, renders step progress
    KnowledgeBrowser/      ← lists ingested files per domain with preview
```

## Build status

| Step | Component | Status |
|---|---|---|
| 1 | `core/models.py` — Document, Chunk, IngestionResult, MemoryRecord, JobStatus | ✅ done |
| 2 | `core/time_grounding/` — TemporalGrounder, GroundingMode, EpisodicMemoryGrounder | ✅ done |
| 3 | `core/readers/spreadsheet.py` — 3-layer pipeline | ✅ done |
| 4 | `core/pipeline/` — IngestionWorker protocol, job state machine, chunking | ✅ done |
| 5 | `adapters/agno/` — thin wrappers for readers + memory store | ✅ done |
| 6 | `examples/personal-aide-minimal/` — end-to-end validation | ⏳ not started |
| 7 | `core/readers/audio.py` and `core/readers/image.py` — STT and OCR | ✅ done |
| 8 | `adapters/langchain/` — LangChain loader wrappers | ✅ done |
| 9 | `ui/components/` — UploadWidget, JobStatusWidget, KnowledgeBrowser | ✅ done |

Primary consumer: `agno-projects/agentic-aide` (personal assistant app). `DEFAULT_USER_ID` fallback (ADR-0009) is superseded there by Supabase Auth (Phase 11) — user identity is always resolved from JWT, never from a config default.

## Install

```bash
# Agno adapter
pip install -e ".[agno]"

# All extras (includes LangChain, dev tools)
pip install -e ".[all]"
```

## Commands

```bash
pytest -q
ruff check agno_plus/
ruff format agno_plus/
```
