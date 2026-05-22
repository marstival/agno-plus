# agno-plus

Reusable extension layer for [Agno](https://github.com/agno-agi/agno) with enhanced ingestion, episodic memory, and UI capabilities.

## Capabilities

- **SpreadsheetReader** — layout-aware Excel/CSV ingestion with merged cell expansion and block detection (TABLE / KV_PAIR / NOTE)
- **AudioReader** — STT via faster-whisper (local) or OpenAI Whisper API
- **ImageReader** — OCR via vision LLM (GPT-4o / Ollama llava)
- **TemporalGrounder** — multilingual (EN / PT-BR / ES) relative date normalization
- **EpisodicMemoryGrounder** — automatic temporal grounding for chat-originated memories
- **IngestionPipeline** — background worker with job state tracking (read → ground → chunk → embed → upsert)
- **UI components** — UploadWidget, JobStatusWidget, KnowledgeBrowser (React / Next.js)

## Design

Framework-agnostic core (`agno_plus/core/`) with zero framework dependencies. Adapters for Agno and LangChain live in `agno_plus/adapters/`.

## Install

```bash
# Agno adapter
pip install "agno-plus[agno] @ git+https://github.com/<org>/agno-plus.git"

# All extras
pip install "agno-plus[all] @ git+https://github.com/<org>/agno-plus.git"
```

## Status

Core layer is implemented: `SpreadsheetReader`, `AudioReader`, `ImageReader`, `TemporalGrounder`, `EpisodicMemoryGrounder`, `IngestionPipeline` with job state tracking, `SourceRef` types, `TracingPort` + `PgTracer` + `LangfuseTracer`. See `AGNO_EXTENSION.md` for the full specification.

Pending: React UI components (`UploadWidget`, `JobStatusWidget`, `KnowledgeBrowser`), LangChain adapter wrappers.

Primary consumer: `agno-projects/agentic-aide` (personal assistant app).
