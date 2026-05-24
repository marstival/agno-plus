# personal-aide-minimal

End-to-end validation of the agno-plus stack: ingest a spreadsheet, store episodic memory, search, and chat — all without agentic-aide or any external service dependency.

## Two entry points

### `agent.py` — CLI, no API key required

Ingests a sample CSV, stores an episodic memory, runs a keyword search, and prints results.

```bash
# From the repo root
pip install -e ".[agno]"
python examples/personal-aide-minimal/agent.py
```

### `app.py` — FastAPI server + React UI

Full-stack demo: file upload, job polling, knowledge browser, RAG chat via OpenAI.

```bash
pip install -r examples/personal-aide-minimal/requirements.txt
pip install -e ".[agno]"

# Terminal 1 — backend
cd examples/personal-aide-minimal
OPENAI_API_KEY=sk-... PYTHONPATH=../.. uvicorn app:app --reload --port 8000

# Terminal 2 — frontend
cd examples/personal-aide-minimal/ui
npm install
npm run dev
```

Open `http://localhost:5173`. Upload `sample_expense_report.csv` via the Ingest tab, then ask questions in Chat.

## What it validates

| agno-plus component | Validated by |
|---|---|
| `SpreadsheetReader` | agent.py + app.py ingest |
| `IngestionPipeline` (sync) | agent.py |
| `BackgroundIngestionPipeline` (threaded) | app.py |
| `TemporalGrounder` | agent.py PERSONAL grounding |
| `EpisodicMemoryGrounder` | agent.py + app.py chat |
| `UploadWidget` | ui/IngestPage.tsx |
| `JobStatusWidget` | ui/IngestPage.tsx |
| `KnowledgeBrowser` | ui/IngestPage.tsx |

`TemporalMergeChunking` and `DomainKnowledge` (Agno-specific adapters) are not exercised here — they require an Agno `Knowledge` + `PgVector` backend and are covered by `tests/adapters/`.
