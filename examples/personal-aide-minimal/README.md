# personal-aide-minimal

A self-contained personal assistant that **exercises every public surface of
agno-plus** in roughly 600 lines of Python. No external auth, no Coordinator
team — just enough wiring to demonstrate the library end-to-end against a
local Postgres + pgvector.

## What it showcases

| agno-plus capability                                  | Module exercising it    | ADR  |
|-------------------------------------------------------|-------------------------|------|
| `IngestionPipeline` (read → ground → chunk → embed → upsert) | `ingestion.py`          | 0007 |
| `SpreadsheetReader` (layout-aware Excel/CSV)          | `ingestion.run_structured` / pipeline registry | 0006 |
| `IntelligentPdfReader`                                | pipeline registry       | 0007 |
| `ImageReader` (vision-LLM OCR)                        | `ingestion.run_image`   | 0003 (exception), 0007 |
| `TextReader`                                          | pipeline registry       | 0007 |
| `TemporalGrounder` (multilingual rule-based)          | `bootstrap.grounder`    | 0003, 0004 |
| `EpisodicMemoryGrounder` (toy demo)                   | `agent.py` CLI          | 0005 |
| `TemporalGrounderDb` (Agno DB wrapper)                | `bootstrap._build_agent` | 0005 |
| `DomainKnowledge` (KnowledgeProtocol + user closure)  | `bootstrap._build_agent` | 0009 |
| `KnowledgeStore` (PgVector, domain/user scoping)      | `bootstrap.knowledge_store` | 0010 |
| `TemporalMergeChunking` (used inside KnowledgeStore)  | implicit                | 0011 |
| `LocalStorageBackend`                                 | `bootstrap.storage`     | 0014 |
| Structured DDL helpers (`create_dynamic_table`, …)    | `ingestion.run_structured` | 0012 |
| `call_llm` (OpenAI/Ollama switch)                     | `ingestion`, `app.infer_schema` | 0015 |
| Source types preserved (`extraction_payload`)         | `ingestion._record_file` | 0007 |
| `UploadWidget` / `JobStatusWidget` / `FileListBrowser` / `TableSchemaEditor` / `JsonPreviewModal` | `ui/src/pages/KnowledgePage.tsx` | UI |

Agno features used directly: `Agent`, `OpenAIChat` / `Ollama`, `PostgresDb`,
`enable_agentic_memory=True`, `add_history_to_context=True`,
`OpenAIEmbedder` / `OllamaEmbedder`, `PgVector`, `Knowledge` registry.

## Module map

```
config.py        env config + USER_ID / DOMAIN_ID constants
bootstrap.py     singleton wiring (engine, storage, grounder, store, pipeline, agent, langfuse)
db.py            schema setup for the aide_files registry
jobs.py          in-memory job tracker mirroring agno-plus JobStatus
ingestion.py     run_semantic / run_structured / run_image  ← the agno-plus showcase
chat.py          Agno Agent + DomainKnowledge + optional Langfuse trace
app.py           FastAPI shell + route handlers (no business logic)
agent.py         standalone CLI demo of IngestionPipeline + EpisodicMemoryGrounder

ui/              Vite + React frontend reusing agno-plus UI components
```

## API surface

```
POST   /ingest                                              → { job_id, file_id }
GET    /jobs/{job_id}                                       → { state, current_step, completed_steps, error }
GET    /files                                               → { files: IngestedFile[] }
GET    /files/{id}/preview                                  → { payload }
GET    /files/{id}/raw                                      → FileResponse
DELETE /files/{id}                                          → { status: "deleted" }
GET    /ingest/structured/{domain}/{table}/sample           → { rows }
GET    /ingest/structured/{domain}/{table}/annotation       → { annotation }
PATCH  /ingest/structured/{domain}/{table}/annotation       → { status }
POST   /domains/{domain}/infer-schema                       → { schema_annotation }
POST   /chat                                                → { reply }
```

## Quick start (Docker Compose)

```bash
cp .env.example .env             # add OPENAI_API_KEY
docker compose up -d
open http://localhost:5173
```

First boot installs agno-plus + agno into the backend container (~60 s).
Follow with: `docker compose logs -f backend`.

## Quick start (local dev)

```bash
docker compose up -d postgres

cd examples/personal-aide-minimal
cp .env.example .env             # add OPENAI_API_KEY
pip install -e "../../[agno,structured,llm,image,pdf]"
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# in another terminal:
cd examples/personal-aide-minimal/ui
npm install
npm run dev
```

## Standalone CLI demo (no Docker, no LLM key)

```bash
python examples/personal-aide-minimal/agent.py
```

Walks through `IngestionPipeline` ingesting a sample CSV, then
`EpisodicMemoryGrounder` grounding "yesterday" into a calendar date.

## Local-only Ollama

```
LLM_BACKEND=ollama
LLM_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434         # or http://host.docker.internal:11434 inside Docker
EMBED_MODEL=nomic-embed-text              # ollama pull nomic-embed-text
VISION_MODEL=llava                        # ollama pull llava
```

## Where this example differs from agentic-aide

`agentic-aide` (the production reference assistant) layers on top of the
same agno-plus library:

- A Coordinator `Team(mode="coordinate")` with sub-agents (Episodic,
  Knowledge, Web). This example uses a single `Agent`.
- Supabase JWT identity + Discord bot. This example uses a fixed
  `USER_ID = "local_user"`.
- DB-persisted job state for restart durability (G-0002). This example
  keeps jobs in memory.
- The `aide_readonly` Postgres role + statement timeout for SQL hardening
  (G-0003). This example does not expose SQL to the agent.

See `agno-plus/docs/boundary-analysis.md` for the full agno-plus vs
application-layer breakdown.

## Optional Langfuse observability

```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d
# Langfuse UI: http://localhost:3001
#   admin@aide.local / aide_admin_password
```

Once `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` are set
in `.env`, every `/chat` call opens a Langfuse trace with the agent's run
attached as a generation span.
