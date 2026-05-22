# agno-plus — Extension Layer Specification

> **Status:** Implemented — core pipeline, readers, time grounding, and pipeline are complete. UI components and LangChain adapters are pending.  
> **Reference application:** `/Users/stival/Projetos/personal-agentic-aide` (read-only reference, do not modify). The `agentic-aide` repo at `agno-projects/agentic-aide` is the primary consumer application.

---

## 1. Purpose

`agno-plus` is a reusable Python + React layer that extends the [Agno](https://github.com/agno-agi/agno) framework with capabilities suited for personal and domain-specific agentic applications:

- Layout-aware spreadsheet ingestion (receipts, financial tables, key-value forms)
- Episodic memory with automatic temporal grounding for conversational channels
- Audio transcription (STT) and image OCR as first-class ingestion readers
- Background ingestion pipeline with job state tracking
- React UI components for upload, job status, and knowledge browsing

`agno-plus` is **not** a vertical application. It is an extension layer. Applications (personal assistant, finance tracker, etc.) are built on top of it.

---

## 2. Goals and Non-Goals

### Goals
- Reusable across multiple agentic applications without forking
- Framework-agnostic core — Agno is the primary adapter target, LangChain is secondary
- Small team shareable via git URL — no PyPI packaging required
- No LLM calls during ingestion — all pipeline steps are deterministic and fast
- UI components that any Next.js application can import

### Non-Goals
- Replacing Agno's agent loop, tool system, or vector store management
- Building a full application (personal assistant is a consumer, not part of this repo)
- PyPI distribution (source-code sharing only for now)
- Supporting every possible framework (only Agno + LangChain adapters initially)

---

## 3. Repository Strategy

Two separate repositories:

```
agno-plus/              ← this new repo (shareable with team, public or private)
personal-aide/          ← separate private repo (rebuilt from scratch as first consumer)
```

`personal-aide` declares `agno-plus` as a git dependency:

```
# personal-aide/requirements.txt
agno-plus @ git+https://github.com/<org>/agno-plus.git
```

Team members get access to `agno-plus` only. The assistant remains private.

---

## 4. Design Principles

### 4.1 Framework Agnosticism via Ports & Adapters

`core/` contains zero framework imports. All Agno or LangChain-specific code lives in `adapters/`. This mirrors the hexagonal architecture of the reference personal assistant codebase.

```
core/readers/base.py       ← Reader as Python Protocol (own interface)
adapters/agno/             ← delegates to core, converts Document types
adapters/langchain/        ← same pattern
```

Adding a new framework adapter costs ~40 lines. Core logic never changes.

### 4.2 Own Document Type

`core/models.py` defines `Document`, `Chunk`, and `IngestionResult` as plain dataclasses. Adapters convert to/from Agno's `Document` or LangChain's `Document`. This keeps the core portable.

### 4.3 Deterministic Ingestion

No LLM calls inside any pipeline step. Temporal grounding uses rule-based multilingual regex. Chunking uses character/token counts with semantic boundary detection. The only LLM calls in the system happen inside the agent's reasoning loop, not during ingestion.

### 4.4 App-Layer Configuration

All behavioral choices (grounding mode per source type, chunking strategy, embedding model, vector backend) are set once at application bootstrap. No runtime user decisions required for pipeline behavior.

---

## 5. Repository Structure

```
agno-plus/
├── agno_plus/
│   ├── __init__.py
│   ├── core/                           ← zero framework deps
│   │   ├── models.py                   ← Document, Chunk, IngestionResult, MemoryRecord
│   │   ├── readers/
│   │   │   ├── base.py                 ← Reader Protocol
│   │   │   ├── spreadsheet.py          ← layout-aware Excel/CSV reader
│   │   │   ├── audio.py                ← Whisper STT reader
│   │   │   └── image.py                ← OCR reader (vision LLM)
│   │   ├── time_grounding/
│   │   │   ├── grounder.py             ← TemporalGrounder (multilingual)
│   │   │   ├── episodic.py             ← EpisodicMemoryGrounder
│   │   │   └── models.py               ← GroundingMode, TimeGrounding
│   │   └── pipeline/
│   │       ├── worker.py               ← IngestionWorker Protocol + job state machine
│   │       └── chunking.py             ← semantic merge chunking utilities
│   └── adapters/
│       ├── agno/
│       │   ├── spreadsheet_reader.py   ← AgnoSpreadsheetReader(agno.Reader)
│       │   ├── audio_reader.py         ← AgnoAudioReader(agno.Reader)
│       │   ├── image_reader.py         ← AgnoImageReader(agno.Reader)
│       │   └── memory_store.py         ← AgnoMemoryStore(MemoryStore Protocol)
│       ├── langchain/
│       │   ├── spreadsheet_loader.py   ← LangChainSpreadsheetLoader
│       │   └── audio_loader.py         ← LangChainAudioLoader
│       └── pgvector/
│           └── memory_store.py         ← PgvectorMemoryStore(MemoryStore Protocol)
├── ui/
│   ├── package.json
│   └── src/
│       └── components/
│           ├── UploadWidget/           ← file upload with type detection + progress
│           ├── JobStatusWidget/        ← polls job status, shows pipeline steps
│           └── KnowledgeBrowser/       ← browse and search ingested memories
├── examples/
│   └── personal-aide-minimal/          ← minimal working assistant using this layer
│       ├── agent.py
│       └── README.md
├── tests/
├── pyproject.toml
└── README.md
```

---

## 6. Core Capabilities

### 6.1 Readers (`core/readers/`)

All readers implement the `Reader` Protocol:

```python
class Reader(Protocol):
    def read(self, source: bytes | str, **kwargs) -> list[Document]: ...
```

#### SpreadsheetReader

Ports the 3-layer pipeline from the reference codebase:

| Layer | Module | Responsibility |
|---|---|---|
| A | `grid_reader` | Parse bytes → sparse `SheetGrid`; expand merged cells (`read_only=False`) |
| B | `block_detector` | BFS connected-component analysis → classify as `TABLE`, `KV_PAIR`, or `NOTE` |
| C | `record_extractor` | Extract typed records (table rows, key-value pairs, free-text notes) |

Key behaviors:
- Merged cell expansion: `read_only=False` + iterating `ws.merged_cells.ranges` to propagate master cell value to all covered coordinates (critical gap vs. Agno's native `ExcelReader` which uses `read_only=True` and silently drops merged content)
- TABLE classification: top-row fill ratio ≥ threshold; data row fill stdev < rejection threshold; confidence scoring on all classifications
- KV_PAIR classification: width == 2, height ≥ min, left-column fill ≥ min
- CSV: `csv.Sniffer()` auto-delimiter detection; UTF-8 with latin-1 fallback
- Supported extensions: `.xlsx`, `.xls`, `.xlsm`, `.csv`, `.tsv`
- Returns one `Document` per detected block (not one per sheet)

#### AudioReader

- Wraps faster-whisper (local) or OpenAI Whisper API
- Backend selected via config (`WHISPER_BACKEND=local|openai`)
- Returns one `Document` per audio file with transcript as content and duration, language as metadata

#### ImageReader

- OCR via vision LLM (OpenAI GPT-4o or Ollama llava)
- Returns one `Document` per image with extracted text
- Suitable for receipts, handwritten notes, scanned documents

---

### 6.2 Time Grounding (`core/time_grounding/`)

#### TemporalGrounder

Multilingual rule-based normalization of relative time references. Supports EN, PT-BR, ES.

```python
class TemporalGrounder:
    def ground(
        self,
        text: str,
        mode: GroundingMode,
        reference_date: datetime,
    ) -> tuple[str, list[TimeGrounding]]: ...
```

`TimeGrounding` carries: `original_expression`, `resolved_date`, `confidence`, `span` (char offsets).

#### GroundingMode

```python
class GroundingMode(str, Enum):
    PERSONAL  = "personal"   # normalize — first-person conversation, receipts
    DOCUMENT  = "document"   # preserve — literary text, reference docs
    AUTO      = "auto"       # sentence-level heuristic: first-person + relative ref → normalize
```

`AUTO` uses sentence-level detection: presence of first-person pronouns co-occurring with a relative time expression triggers normalization for that sentence only. Handles mixed documents without requiring document-level classification.

#### EpisodicMemoryGrounder

Wraps any `MemoryStore` implementation. Applies `PERSONAL` mode with `reference_date=now()` automatically for all chat-channel-originated memories.

```python
class EpisodicMemoryGrounder:
    def __init__(self, store: MemoryStore, grounder: TemporalGrounder): ...

    def store(self, text: str, user_id: str, **meta) -> MemoryRecord:
        grounded_text, groundings = self._grounder.ground(
            text,
            mode=GroundingMode.PERSONAL,
            reference_date=datetime.now(timezone.utc),
        )
        event_at = groundings[0].resolved_date if groundings else None
        return self._store.upsert(
            content=grounded_text,
            metadata={"event_at": event_at, "user_id": user_id, **meta},
        )
```

**Grounding mode per source — app-layer config:**

| Source | Mode | Set by |
|---|---|---|
| Chat channel (any) | `PERSONAL` | Hardcoded in `EpisodicMemoryGrounder` |
| Receipt / invoice image | `PERSONAL` | App config at `ImageReader` instantiation |
| Financial spreadsheet | `PERSONAL` | App config at `SpreadsheetReader` instantiation |
| PDF book / reference doc | `DOCUMENT` | App config at reader instantiation |
| Unknown upload | `AUTO` | Default when mode not specified |

The grounding mode is **never a user-facing runtime decision**. It is set once at application bootstrap per source type.

---

### 6.3 Ingestion Pipeline (`core/pipeline/`)

#### IngestionWorker Protocol

```python
class IngestionWorker(Protocol):
    def submit(self, source: bytes | str, filename: str, meta: dict) -> str: ...  # returns job_id
    def status(self, job_id: str) -> JobStatus: ...
```

#### Job State Machine

```
pending → processing → completed
                    ↘ failed
```

Each job tracks steps: `read → ground → chunk → embed → upsert`.

After each step, `JobStatus` is updated:

| Field | Set after step | Content |
|---|---|---|
| `extraction_payload` | READ | `list[dict]` — each `Document` from the reader serialized to `{id, source_type, source_name, content, metadata}` |
| `chunks_count` | CHUNK | `int` — number of chunks produced |
| `completed_steps` | each step | list of completed `JobStep` values |
| `state` | end | `completed` or `failed` |

`extraction_payload` is available via `pipeline.status(job_id).extraction_payload` after the job finishes. Application code can persist this to a DB for user-facing extraction preview without re-running the reader.

#### Pipeline Steps (ordered)

1. **Read** — invoke the appropriate `Reader` based on file extension
2. **Ground** — apply `TemporalGrounder` with mode from reader config
3. **Chunk** — semantic merge chunking (split on sentence boundaries, merge small chunks up to token limit)
4. **Embed** — call embedding backend (OpenAI / Ollama)
5. **Upsert** — write chunks to vector store via `MemoryStore` adapter

---

### 6.4 MemoryStore Protocol

```python
class MemoryStore(Protocol):
    def upsert(self, content: str, metadata: dict) -> MemoryRecord: ...
    def search(self, query: str, user_id: str, **kwargs) -> list[MemoryRecord]: ...
    def delete(self, record_id: str) -> None: ...
```

Implementations: `AgnoMemoryStore`, `PgvectorMemoryStore`. Adding Qdrant is a new adapter file.

---

## 7. Adapters

### 7.1 Agno Adapter Pattern

Each adapter subclasses Agno's base class and delegates to the corresponding core reader:

```python
# adapters/agno/spreadsheet_reader.py
from agno.document.reader.base import Reader as AgnoReader
from agno_plus.core.readers.spreadsheet import SpreadsheetReader

class AgnoSpreadsheetReader(AgnoReader):
    def __init__(self, **kwargs):
        self._core = SpreadsheetReader(**kwargs)

    def read(self, source, **kwargs) -> list[AgnoDocument]:
        return [_to_agno_doc(d) for d in self._core.read(source, **kwargs)]
```

### 7.2 LangChain Adapter Pattern

```python
# adapters/langchain/spreadsheet_loader.py
from langchain_core.document_loaders import BaseLoader
from agno_plus.core.readers.spreadsheet import SpreadsheetReader

class LangChainSpreadsheetLoader(BaseLoader):
    def __init__(self, file_path: str, **kwargs):
        self._core = SpreadsheetReader(**kwargs)
        self._path = file_path

    def load(self) -> list[LangChainDocument]:
        with open(self._path, "rb") as f:
            docs = self._core.read(f.read(), filename=self._path)
        return [_to_lc_doc(d) for d in docs]
```

---

## 8. UI Components (`ui/`)

React components designed to be imported into any Next.js application. No Storybook or component registry required — source code is copied or imported directly.

| Component | Responsibility |
|---|---|
| `UploadWidget` | File drop zone; detects type (spreadsheet / audio / image / text); shows accepted formats; triggers `POST /ingest` |
| `JobStatusWidget` | Polls job status endpoint; shows step-by-step progress (read → ground → chunk → embed → upsert); handles failed state |
| `KnowledgeBrowser` | Lists ingested memories with search; shows source file, event_at timestamp (grounded), block type metadata |

Components are backend-agnostic — they accept endpoint URLs as props so they work with any FastAPI or other backend that implements the ingestion API contract.

---

## 9. Application Bootstrap Pattern

How a consumer application (e.g., personal-aide) wires the layer:

```python
# personal-aide/backend/app/core/bootstrap.py

from agno_plus.core.time_grounding.grounder import TemporalGrounder
from agno_plus.core.time_grounding.episodic import EpisodicMemoryGrounder
from agno_plus.adapters.agno.spreadsheet_reader import AgnoSpreadsheetReader
from agno_plus.adapters.agno.audio_reader import AgnoAudioReader
from agno_plus.adapters.agno.memory_store import AgnoMemoryStore
from agno_plus.core.pipeline.worker import IngestionPipeline

grounder = TemporalGrounder(locales=["en", "pt-BR", "es"])

knowledge_base = AgnoKnowledgeBase(...)  # Agno's KB pointing at vector store

memory = EpisodicMemoryGrounder(
    store=AgnoMemoryStore(knowledge_base),
    grounder=grounder,
)

pipeline = IngestionPipeline(
    readers={
        ".xlsx": AgnoSpreadsheetReader(grounding_mode="personal"),
        ".xls":  AgnoSpreadsheetReader(grounding_mode="personal"),
        ".mp3":  AgnoAudioReader(),
        ".m4a":  AgnoAudioReader(),
        ".jpg":  AgnoImageReader(grounding_mode="personal"),
        ".pdf":  AgnoImageReader(grounding_mode="auto"),
    },
    memory_store=AgnoMemoryStore(knowledge_base),
    grounder=grounder,
)

agent = Agent(
    knowledge=knowledge_base,
    tools=[
        StoreMemoryTool(memory),   # chat → EpisodicMemoryGrounder → vector store
        SearchMemoryTool(memory),
        WebSearchTool(),
    ],
)
```

---

## 10. Build Order

Build and validate in this sequence so each layer is testable in isolation:

1. **`core/models.py`** — `Document`, `Chunk`, `IngestionResult`, `MemoryRecord`, `JobStatus`
2. **`core/time_grounding/`** — `TemporalGrounder`, `GroundingMode`, `EpisodicMemoryGrounder`
3. **`core/readers/spreadsheet.py`** — port 3-layer pipeline from reference codebase
4. **`core/pipeline/`** — `IngestionWorker` protocol, job state machine, chunking utilities
5. **`adapters/agno/`** — thin wrappers for spreadsheet, audio, image readers + memory store
6. **`examples/personal-aide-minimal/`** — end-to-end validation: ingest a spreadsheet, ask a question
7. **`core/readers/audio.py`** and **`core/readers/image.py`** — STT and OCR readers
8. **`adapters/langchain/`** — LangChain loader wrappers
9. **`ui/components/`** — UploadWidget, JobStatusWidget, KnowledgeBrowser

Each step has a natural test boundary. Steps 1–6 prove the core value proposition before touching UI or secondary adapters.

---

## 11. Key Differences vs. Agno Native Capabilities

| Capability | Agno native | agno-plus |
|---|---|---|
| Excel reader | `read_only=True` — merged cells silently dropped; one Document per sheet | `read_only=False`; merged cell expansion; BFS block detection; one Document per block |
| Temporal grounding | None | Multilingual (EN/PT-BR/ES); PERSONAL/DOCUMENT/AUTO modes; `event_at` metadata on every memory |
| Episodic memory | Manual tool call; no time normalization | `EpisodicMemoryGrounder` wraps any store; grounding automatic on all chat-originated memories |
| STT ingestion | No native reader | `AudioReader` via faster-whisper (local) or OpenAI Whisper |
| OCR ingestion | No native reader | `ImageReader` via vision LLM (GPT-4o / llava) |
| Background pipeline | No native job queue | `IngestionPipeline` with job state machine and step tracking |
| Upload UI | AgnoOS portal (cloud-hosted) | Self-hosted React components; backend-agnostic |

---

## 12. Open Questions

- [ ] Repo name: `agno-plus` is a working name — confirm or rename before creating the repo
- [ ] Whether to contribute `SpreadsheetReader` (merged cell fix) upstream to Agno as a PR alongside keeping the extended version here
- [ ] LangChain adapter priority — build after Agno adapter is validated, or defer entirely
- [ ] Whether `KnowledgeBrowser` UI component needs pagination/filtering at MVP or search-only is sufficient
