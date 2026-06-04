# personal-aide-minimal

A complete, self-contained personal assistant built on **agno-plus** — showcasing how the library's modular components combine into a working application.

## What you get

| Feature | agno-plus component |
|---|---|
| File upload + background ingestion | `UploadWidget` + `JobStatusWidget` |
| Ingested file list with delete/edit | `FileListBrowser` |
| CSV/Excel → PostgreSQL table | `create_dynamic_table`, `bulk_insert`, `infer_column_types` |
| Column annotation + LLM auto-fill | `TableSchemaEditor` + `call_llm()` |
| Semantic search (pgvector RAG) | `KnowledgeStore` |
| Raw file serving | `LocalStorageBackend` |
| Chat with knowledge retrieval | `call_llm()` + `KnowledgeStore.search()` |
| Observability (optional) | Langfuse v3 |

## Quick start (Docker Compose)

```bash
# 1. Clone + configure
cp .env.example .env
#    → Edit .env and add your OPENAI_API_KEY

# 2. Start everything (postgres + backend + frontend)
docker compose up -d

# 3. Open the app
open http://localhost:5173

# 4. (Optional) Add Langfuse observability
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d
#    → Langfuse UI at http://localhost:3001
#       Email: admin@aide.local  Password: aide_admin_password
```

> **First run note:** The backend container installs agno-plus on startup (~60 s). Watch progress with `docker compose logs -f backend`.

## Quick start (local dev — faster iteration)

```bash
# Terminal 1 — PostgreSQL only
docker compose up -d postgres

# Terminal 2 — Backend
cd examples/personal-aide-minimal
cp .env.example .env            # add OPENAI_API_KEY
pip install -e "../../[agno,structured,llm]"
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# Terminal 3 — Frontend
cd examples/personal-aide-minimal/ui
npm install
npm run dev
```

## Ollama (local-only, no API key)

```
LLM_BACKEND=ollama
LLM_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434   # or http://host.docker.internal:11434 inside Docker
EMBED_MODEL=nomic-embed-text        # ollama pull nomic-embed-text
```

## Architecture

```
app.py                       ← single-file FastAPI backend
│
├── LocalStorageBackend      ← raw file → /uploads/{user}/{file_id}_{name}
├── KnowledgeStore           ← pgvector chunks in ai.aide_knowledge_chunks
│     └── search()           ← JSONB-filtered by user_id + domain_id
├── create_dynamic_table()   ← CSV/Excel headers → sd_personal_{name} table
├── bulk_insert()            ← row-by-row upsert with type coercion
└── call_llm()               ← schema annotation + RAG prompt
```

```
ui/src/
├── App.tsx                  ← two-tab shell (Chat / Knowledge)
├── pages/ChatPage.tsx       ← message thread + /chat endpoint
└── pages/KnowledgePage.tsx  ← UploadWidget + FileListBrowser + TableSchemaEditor
```

## API surface

```
POST /ingest                → { job_id, file_id }
GET  /jobs/{job_id}         → { state, current_step, completed_steps, error }
GET  /files                 → { files: IngestedFile[] }
DELETE /files/{id}          → { status: "deleted" }
GET  /files/{id}/raw        → FileResponse
GET  /ingest/structured/{domain}/{table}/sample  → { rows }
PATCH /ingest/structured/{domain}/{table}/annotation
POST /domains/{domain}/infer-schema → { schema_annotation }
POST /chat                  → { reply }
```
