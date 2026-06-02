# LinkedIn Post — agno-plus

---

**Building a production-ready AI assistant with Agno taught me what the framework doesn't give you out of the box.**

Agno is one of the cleanest Python frameworks for building multi-agent systems I've worked with. Agents, Teams, memory, tools, vector stores — the primitives are solid and the API is intuitive. If you haven't looked at it yet, it's worth your time.

But when I started building a personal assistant that ingests real-world documents — invoices, spreadsheets, voice memos, scanned receipts — I kept hitting the same ceiling. The framework handles *what* to do with content once it's chunked and embedded. The gap is everything that happens before and around that.

So I built **agno-plus**: an open-source extension layer that sits between your documents and Agno's agent loop. Here's what it adds:

**Layout-aware ingestion**
Agno's native Excel reader uses `read_only=True` and silently drops merged cells. On any real financial spreadsheet, that means losing half your data. agno-plus reimplements this with merged-cell expansion, BFS block detection (TABLE / KV_PAIR / NOTE), and one document per semantic block — not one per sheet.

PDF tables are equally painful. agno-plus adds a stream extractor that recovers tabular structure from borderless PDFs (bank statements, generated invoices) where no bounding-box metadata exists.

**Temporal grounding for episodic memory**
When a user says "I had a meeting last Tuesday", Agno stores exactly that string. Query it two weeks later and it's meaningless. agno-plus normalizes relative time expressions at ingestion time — multilingual (EN / PT-BR / ES), with PERSONAL / DOCUMENT / AUTO modes — so `event_at` in every memory record carries an absolute timestamp, not a relative phrase.

**Audio and image ingestion as first-class readers**
faster-whisper (local) or OpenAI Whisper for voice memos. Vision LLM for receipts and scanned documents. Same `read() → chunk → embed → upsert` pipeline as every other reader.

**Structured domains: SQL + semantic in one step**
Some documents belong in SQL, not a vector store. agno-plus includes DDL utilities (`create_dynamic_table`, `infer_column_types`, `bulk_insert`) for dynamic PostgreSQL tables alongside a dual-write pattern: when a PDF is ingested as structured data, all its prose blocks are also written to the semantic store. SQL for filtering and aggregation, vector search for context — neither alone is enough.

**A unified LLM call helper**
Every service that needed LLM-extracted metadata re-implemented the same OpenAI / Ollama switch. `call_llm()` eliminates that: one function, both backends, JSON mode, configurable tokens.

**KnowledgeStore with domain/user isolation**
Agno's PgVector is great at storing vectors. Scoping search results to a specific user and domain requires JSONB containment filters that aren't built in. `KnowledgeStore` wraps PgVector with `user_id` and `domain_id` isolation, chunking via `TemporalMergeChunking`, and an `ingest_documents()` method for bulk dual-write ingestion.

---

The architecture stays honest: `agno_plus/core/` has zero framework dependencies. Adapters for Agno, LangChain, pgvector, and Langfuse live separately. Adding a new framework adapter is ~40 lines.

The library is consumed by a personal assistant I use daily. The same patterns apply to any document-heavy Agno application: finance trackers, knowledge bases, compliance tools.

If you're building on Agno and hitting any of these gaps, the code is open.

→ github.com/marstival/agno-plus

---

*#agno #aiengineering #llm #rag #python #openai #softwareengineering*

---

## Deep dive: Episodic memory vs. ingested knowledge — two different systems

This distinction matters more than it looks. In the assistant I built, there are two things that feel like "memory" to the user but are architecturally nothing alike.

**Ingested knowledge** is what you upload. A PDF, a spreadsheet, a voice memo. You trigger the pipeline explicitly. The content goes through a reader, gets chunked, embedded, and written to a pgvector table (`ai.agno_knowledge_chunks`). Every chunk carries `user_id` and `domain_id` in its metadata. Retrieval is semantic: cosine similarity against an embedding, filtered by those two fields. The agent that handles this (`KnowledgeAgent`) doesn't know anything about conversations — it knows about files.

**Episodic memory** is what you say. When you tell the assistant "I prefer summaries in bullet points" or "I have a client call on Friday", the Coordinator doesn't store that in the vector store. It uses Agno's native `MemoryManager` with `enable_agentic_memory=True`, which writes to a relational table called `agno_memories`. No embedding, no chunking. Each row is a short text fact with a `user_id`, a topic list, and a timestamp. The LLM decides what's worth keeping from each conversation turn — the user never explicitly says "remember this".

The pipelines are completely different:

```
Uploaded file
  → reader (SpreadsheetReader / PdfReader / AudioReader)
  → TemporalGrounder [DOCUMENT or AUTO mode]
  → TemporalMergeChunking
  → embedder (OpenAI / Ollama)
  → KnowledgeStore.upsert() → ai.agno_knowledge_chunks (pgvector)

User says something affirmative in chat
  → Coordinator LLM extracts the fact
  → TemporalGrounderDb.upsert_user_memory() [intercepts Agno's write path]
  → TemporalGrounder [PERSONAL mode, reference_date = now()]
  → agno_memories table (relational, no embedding)
```

That `TemporalGrounderDb` intercept is the key piece agno-plus adds. Agno's `MemoryManager` writes to a `BaseDb` implementation. agno-plus wraps that with a transparent proxy: every `upsert_user_memory` call is intercepted, the memory text is run through the grounder, relative time expressions are resolved to absolute dates, and an `event_at:YYYY-MM-DD` topic tag is attached — before the record ever reaches the database. The agent and the MemoryManager don't know this happened.

This means "I had a dentist appointment last Tuesday" stored in January becomes "I had a dentist appointment on 2026-01-27 (event_at:2026-01-27)" in the database. Query it in March and the date is still right. Without the intercept, both Agno's MemoryManager and the embedding layer would store the phrase "last Tuesday" literally — meaningless three months later.

The two stores are queried by different agents for different reasons. `EpisodicAgent` recalls facts the user stated directly. `KnowledgeAgent` searches documents the user uploaded. The Coordinator routes between them — it doesn't mix the two systems.

---

## Deep dive: Multi-user data isolation — what Agno provides vs. what you have to add

Agno handles user isolation for episodic memory correctly out of the box. `MemoryManager` scopes all reads and writes to the current session's `user_id` — two users sharing the same PostgreSQL instance cannot read each other's `agno_memories` rows.

The vector store is a different story.

Agno's `PgVector.search()` finds the N nearest neighbors by cosine distance across the entire table. There is no built-in per-user or per-tenant scope. In a single-user local deployment that's fine. In any multi-user deployment, every user gets back results from every other user's documents — silently, with no error.

agno-plus closes this gap with JSONB containment filtering. Every chunk written by `KnowledgeStore.upsert()` or `insert_document()` embeds `user_id` and `domain_id` into the `meta_data` JSONB column of the pgvector table. Every `search()` call constructs a filter:

```python
filters: dict = {"user_id": user_id}
if domain_id:
    filters["domain_id"] = domain_id

docs = self._vdb.search(query=query, limit=top_k, filters=filters)
```

pgvector evaluates this as a `@>` containment check on the JSONB column before ranking by distance. A user querying "revenue forecast" gets back only chunks from their own documents. Narrowing by `domain_id` scopes further to a specific knowledge domain (one per topic area the user creates).

The isolation is enforced at two levels. At write time: `upsert()` raises `ValueError` if `user_id` is missing from metadata — malformed writes are rejected, not silently stored globally. At read time: the `DomainKnowledge` adapter that exposes `search_knowledge` as an agent tool captures `user_id` from the Agno run context at agent-setup time and closes over it:

```python
def get_tools(self, **kwargs):
    run_context = kwargs.get("run_context")
    user_id = getattr(run_context, "user_id", None) or ""
    return [self._make_search_fn(user_id)]  # user_id is baked in
```

The agent's tool function never receives `user_id` as a parameter the LLM could manipulate. It's captured from the authenticated run context and injected invisibly. An agent cannot search another user's knowledge even if it tries to, because it has no mechanism to pass a different `user_id` — the value is not in the tool's signature.

For structured SQL tables the isolation is by naming convention: every dynamic table is named `sd_{domain_id_short}_{label}`. The Coordinator pre-loads the user's domain inventory into its system prompt at request time — it only knows about the current user's domain IDs. A query to a `sd_*` table for a domain the user doesn't own returns an empty result or a SQL error, not another user's data.

This is not a complete security boundary on its own — it relies on the application layer enforcing that `user_id` comes from a verified JWT, not from user input. But it means the data layer is not accidentally porous by default, which is the more common failure mode in shared-database AI applications.

---

*#agno #aiengineering #llm #rag #python #multitenancy #softwareengineering*
