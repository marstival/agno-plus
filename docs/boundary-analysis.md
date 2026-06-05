# agno-plus vs Application Layer — Boundary Analysis

This document explains the design principle behind what lives in `agno-plus`
versus what stays in the consuming application, using `agentic-aide` and
`examples/personal-aide-minimal` as the two reference consumers. It also flags
the boundary cases that are deliberately ambiguous.

The companion ADRs (`docs/adr/`) record each decision; this document is the
narrative that ties them together.

---

## 1. The guiding question

> _If a second team built a different Agno-based assistant tomorrow, would they
> reach for this exact piece of code, or would they want a different version of
> it?_

If the answer is **"they would reach for the same code"**, it belongs in
`agno-plus`. If the answer is **"they would want a different version"**, it
belongs in the application.

This is the same boundary that distinguishes a library from an application
generally; the value of writing it down explicitly is that it forces every
proposed addition to `agno-plus` to be justified in those terms.

## 2. What belongs in `agno-plus`

### 2.1 Reusable primitives that fill Agno gaps

Agno covers a lot — agent orchestration, native memory, knowledge bases, agent
teams, session history. `agno-plus` does not duplicate any of that (ADR-0005,
agentic-aide ADR-0003). It adds the things Agno doesn't ship:

| Capability                                  | Why agno-plus                                                | ADR |
|---------------------------------------------|--------------------------------------------------------------|-----|
| Layout-aware spreadsheet ingestion          | Agno's `ExcelReader` drops merged cells (`read_only=True`).  | 0006 |
| Deterministic multilingual temporal grounding | Not provided by Agno; LLM-based grounding is too expensive at memory-write rate. | 0003, 0004 |
| Episodic-grounding hook                     | Wraps Agno DB or any MemoryStore — no fork.                  | 0005 |
| Background ingestion pipeline + JobStatus contract | A reusable job model with extraction_payload and progress steps. | 0007 |
| Typed source-ref union                      | Consistent citation shape across `EpisodicRef`, `KnowledgeRef`, `DataRef`, `WebRef`. | 0008 |
| `DomainKnowledge` (KnowledgeProtocol)       | Multi-tenant RAG with run-context `user_id` closure.         | 0009 |
| `KnowledgeStore` (PgVector wrapper)         | Domain/user-scoped semantic store with content-hash dedupe.  | 0010 |
| `TemporalMergeChunking` (Agno ChunkingStrategy) | Hooks chunking without overriding `Knowledge.insert()`.  | 0011 |
| Dynamic structured tables (DDL helpers)     | Standardizes CSV/XLSX → SQL across apps.                     | 0012 |
| `TracingPort` (Protocol + adapters)         | Pluggable observability — DB lineage + Langfuse.             | 0013 |
| `StorageBackend` (Protocol + local default) | Decouples raw-file persistence from FastAPI route shape.     | 0014 |
| Provider-switching `call_llm()`             | Removes per-service OpenAI/Ollama branching for narrow extraction prompts. | 0015 |

### 2.2 Cross-cutting models and protocols

Owning `Document`, `Chunk`, `MemoryRecord`, `JobStatus`, and the `SourceRef`
union in `core/` (ADR-0002) lets the same library serve Agno-native and
LangChain-native consumers without forcing either to import the other framework
(ADR-0001).

### 2.3 What "good agno-plus code" looks like

- Lives in `core/` only when it has zero framework imports.
- Lives in `adapters/<framework>/` when it talks to a specific framework.
- Has a Protocol-shaped interface in core whenever there is more than one
  reasonable adapter shape (storage, memory, tracing, embedder).
- Is configured at construction or `submit()` time — never at request time
  by an end user (grounding mode, chunk size, backend).
- Survives a hypothetical Agno major-version bump because it only touches
  Agno's documented public surface (`KnowledgeProtocol`, `ChunkingStrategy`,
  `BaseDb`, `PgVector`).

---

## 3. What stays in the application

### 3.1 Product decisions

The Coordinator team, the routing instructions, the prompt templates, the
domain inventory model, intent taxonomy — all of these are choices about
*this* product. A different assistant would make different choices. They
belong in the application (`agentic-aide/backend/app/`).

| Concern                                | Lives where                  | Why                                                  |
|----------------------------------------|------------------------------|------------------------------------------------------|
| Sub-agents (Episodic, Knowledge, Web)  | Application                  | Capability composition; reflects the assistant's product surface. |
| Coordinator `Team(mode="coordinate")`  | Application                  | Routing instructions are product-specific.            |
| Intent taxonomy and intent hints       | Application                  | Same as above.                                       |
| Domain CRUD                            | Application                  | The "domain" concept is a product abstraction, not a library one. |
| Schema annotation editor + UI          | Application                  | Reflects how this product wants users to describe tables. |
| Discord bot + slash commands           | Application                  | Channel adapter is per-product.                      |

### 3.2 Identity and platform integrations

`agno-plus` enforces identity but does not produce it (G-0001). Supabase Auth,
JWT validation, the chat proxy on port 8000, AgentOS hosting on port 7777 —
all platform-shaped decisions, owned by the application (agentic-aide
ADR-0004, ADR-0009, ADR-0010, ADR-0011).

### 3.3 Operational shape

How the app survives a restart (ingestion durability: agentic-aide ADR-0014),
how it persists raw files for the long term (storage backend choice, app side
of agno-plus ADR-0014), what role the SQL agent runs as (agentic-aide
ADR-0013, agno-plus guidance G-0003) — all decisions the application makes
when wiring `agno-plus` components together.

### 3.4 Frontend

The agentic-aide React frontend exists at the application level. `agno-plus`
ships a `ui/` package with three components (`UploadWidget`,
`JobStatusWidget`, `KnowledgeBrowser`, plus `FileListBrowser`,
`TableSchemaEditor`, `JsonPreviewModal`) — they are backend-agnostic and
consumable from any Next.js or Vite app. Pages that *compose* those
components (a Knowledge tab, a Chat tab) are application code.

---

## 4. Boundary cases — explicit calls

Some pieces could plausibly live in either place. The decisions below are
deliberate.

### 4.1 `KnowledgeAwarePipeline` — application-side subclass

`agno-plus` ships `IngestionPipeline` (synchronous, in-memory). agentic-aide
subclasses it as `KnowledgeAwarePipeline` to delegate CHUNK/EMBED/UPSERT to
`KnowledgeStore.insert_document()` (agentic-aide ADR-0007). The subclass
lives in the application even though it is short and reusable.

Reason: the choice to dual-write to a domain-scoped semantic store is a
product decision, not a library one. Apps that don't use `KnowledgeStore`
(e.g. apps using a different vector backend, or apps that don't dual-write)
would not benefit from this subclass.

### 4.2 `TemporalGrounderDb` vs `EpisodicMemoryGrounder` — both in agno-plus

Two wrappers exist (ADR-0005). Both are in agno-plus because both serve a
different integration shape: apps that wire their own `MemoryStore`
(EpisodicMemoryGrounder) and apps that use Agno's native agentic memory
(`TemporalGrounderDb`). Either is reusable across consumers.

### 4.3 `StorageBackend` — promoted from app to agno-plus

agentic-aide's ADR-0006 placed `StorageBackend` in the application on the
grounds that no second consumer existed yet. The second consumer
(`examples/personal-aide-minimal`) exists now, so the port is promoted to
agno-plus (ADR-0014). Local implementation stays in agno-plus; cloud
implementations (S3, GCS) are likely to live alongside, deployment-shape
permitting.

### 4.4 `call_llm()` — adapter, not core

It calls the network and depends on `openai` / `httpx`. It cannot live in
`core/` (ADR-0001). It belongs in `adapters/llm.py` (ADR-0015) and is the
right tool only for narrow one-shot prompts. Real agent loops use Agno
`Agent` / `Team`, not `call_llm()`.

### 4.5 SQL hardening — application responsibility

The role and timeout (G-0003) are application-deployment choices.
`agno-plus` provides the hook (`create_dynamic_table(..., grant_to=...)`)
and documents the pattern but does not create the role or enforce the
timeout. Apps that deploy structured-domain SQL to real users must
implement both layers themselves.

### 4.6 Identity required at the boundary — partial library enforcement

`KnowledgeStore.upsert()` raises on missing `user_id`. `DomainKnowledge`
binds `user_id` from `run_context` at run time. `EpisodicMemoryGrounder`
takes `user_id` as a required positional. But routing authentication to
the right caller (Supabase JWT, Discord bot secret) is application work.
The library guards the boundary; it does not produce the identity.

---

## 5. What we deliberately did **not** put in agno-plus

| Capability                                  | Where                       | Why not in agno-plus                                 |
|---------------------------------------------|-----------------------------|------------------------------------------------------|
| Coordinator team + routing prompt            | agentic-aide application    | Product-specific.                                    |
| Intent classifier (keyword hints)            | agentic-aide application    | Product-specific; the agent decides routing anyway (agentic-aide ADR-0002). |
| Discord bot, slash commands, link codes     | agentic-aide application    | Channel-specific integration.                        |
| Supabase JWT validation                     | agentic-aide application    | Platform-specific.                                   |
| AgentOS hosting + port-8000 chat proxy      | agentic-aide application    | Platform-specific (agentic-aide ADR-0004, ADR-0011).  |
| `aide_readonly` Postgres role               | agentic-aide application    | Deployment-shape; agno-plus provides the GRANT hook only (G-0003). |
| `ingested_files` table model + DB-backed job state | agentic-aide application | Agno-plus exposes the contract (`JobStatus.extraction_payload`, `chunks_count`) but does not persist anything. |
| 5-table domain inventory data model          | agentic-aide application    | Reflects this product's UX (ADR-0015 in agentic-aide). |
| Frontend Knowledge tab layout               | agentic-aide application    | Composition of agno-plus UI primitives + product decisions about page shape. |

---

## 6. Simplification examples

The boundary delivers real simplification in agentic-aide. Concrete examples:

- **Ingestion route.** The route receives a file, persists raw bytes via
  `StorageBackend`, dispatches `IngestionPipeline.submit()`, then reads
  `extraction_payload` and `chunks_count` from `JobStatus` after the job
  completes. None of the per-step orchestration is in the application.
- **Episodic memory.** Wrap `PostgresDb(...)` with `TemporalGrounderDb(...)`
  and pass the wrapper to the Coordinator. Native agentic memory keeps
  working; every memory write is silently grounded. No application code
  touches grounding logic.
- **RAG retrieval.** `Agent(knowledge=DomainKnowledge(store))`. The
  `search_knowledge` tool is generated per run with the correct
  `user_id` from `run_context`. The application never writes a tool
  decorator for knowledge search.
- **Tracing.** `PgTracer(...)` and `LangfuseTracer(...)` are constructed at
  bootstrap and passed to sub-agents as optional dependencies. Removing or
  swapping a tracer changes one config line.

---

## 7. Mental model summary

> `agno-plus` is the **substrate**. The application is the **product**.

The substrate covers:

- Anything an Agno team would re-implement on their next assistant.
- Anything Agno could in principle do, but doesn't yet — closing those
  gaps with extension points that survive Agno upgrades.
- Anything that benefits from a second-consumer test (currently
  `personal-aide-minimal`).

The product covers:

- Anything that reflects how *this* assistant talks, routes, authenticates,
  presents data, or integrates with operational tooling.
