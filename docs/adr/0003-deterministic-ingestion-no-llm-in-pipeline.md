# Ingestion pipeline steps are deterministic — no LLM calls inside read/ground/chunk

**Status:** Accepted

## Decision

`IngestionPipeline.submit()` runs `read → ground → chunk → embed → upsert` without any LLM call. Specifically:

- **Read** uses local parsers (`openpyxl`, `pypdf`, `csv`) and, for `AudioReader`, may call a transcription backend (faster-whisper or OpenAI Whisper) — speech-to-text is not "LLM reasoning" for this purpose.
- **Ground** uses `TemporalGrounder` — pure-Python regex multilingual matcher; no model invocation.
- **Chunk** uses `chunk_text_structured` — structural block detection + token-budget merging; no model invocation.
- **Embed** calls the embedder configured on the vector store (OpenAI, Ollama, etc.). This is mechanical encoding, not a generative LLM call.
- **Upsert** writes to the configured store.

LLM reasoning happens only above the pipeline — inside the agent loop, or in optional opt-in flows like structured-domain LLM column annotation (`adapters/llm.py` called by the application layer).

`ImageReader` is the one core reader that legitimately depends on a vision LLM for OCR. It is documented as a paid-call reader and is excluded from the deterministic guarantee. Applications that need pure-deterministic ingestion can swap it for a Tesseract reader without touching the pipeline.

## Rationale

Deterministic ingestion has three concrete benefits in production assistants:

1. **Reproducibility.** Re-ingesting a file yields the same chunks. CI tests on `read → ground → chunk` are stable; reference outputs do not drift as upstream model weights change.
2. **Cost and latency.** No per-document LLM call means ingesting 10 PDFs costs the same as ingesting 1, modulo embedding. Backend pipelines do not block on a 6-second LLM call for routine ingestion.
3. **Observability.** Pipeline steps either succeed or fail on inputs the application controls. A non-deterministic step turns intermittent ingestion failures from "fix the parser" into "tune the prompt or retry the model."

## Alternatives considered

**LLM-based chunking.** Send each document to an LLM and ask it to emit semantic chunks. Quality can be higher for prose, but cost scales linearly with corpus size and chunks differ run-to-run, breaking dedup hashes. Rejected as a default; an opt-in `LLMChunkingStrategy` adapter could be added without changing core.

**LLM-based temporal grounding.** Replace `TemporalGrounder` regex with a function-calling LLM. Higher coverage on edge cases (e.g. "the Thursday two weeks before the wedding") at the cost of API spend on every memory write and unverifiable correctness. The rule-based approach handles ~95% of relative-date patterns in EN/PT/ES and is the right default.

## Consequences

- Tests for readers, grounder, and chunker run offline without API keys.
- Adding a new LLM-driven enrichment (e.g. entity extraction over text) is done in the application layer between the pipeline result and the vector store write, not by mutating pipeline steps.
- `ImageReader` is the documented exception. Its `__init__` takes the backend/model/api_key explicitly so the dependency is loud.
